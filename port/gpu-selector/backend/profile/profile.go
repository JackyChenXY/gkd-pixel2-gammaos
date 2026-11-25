// SPDX-License-Identifier: Apache-2.0
package profile

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

//go:embed profile.json
var layout []byte

type Component struct {
	Path         string
	Size         int64
	Hash         string
	Source, Dest [][2]int64
}
type Profile struct {
	Files []Component

	RawSize   int64  `json:"raw_size"`
	SlotSize  int64  `json:"slot_size"`
	EmptyHash string `json:"empty_hash"`
	FullHash  string `json:"full_hash"`
}

var Board Profile

func init() {
	if err := json.Unmarshal(layout, &Board); err != nil {
		panic(err)
	}
}

var ErrFormat = errors.New("unsupported input format")
var ErrMismatch = errors.New("driver files do not match the supported Rockchip Android release")

func hash(b []byte) string { sum := sha256.Sum256(b); return hex.EncodeToString(sum[:]) }
func verified(c Component, b []byte) ([]byte, error) {
	if int64(len(b)) != c.Size || hash(b) != c.Hash {
		return nil, fmt.Errorf("%w: %s", ErrMismatch, c.Path)
	}
	return b, nil
}

// A source returns only the allowlisted component requested by this build.
type Source func(Component) ([]byte, error)

func directory(root string) Source {
	return func(c Component) ([]byte, error) {
		p := filepath.Join(root, filepath.FromSlash(c.Path))
		f, e := os.Open(p)
		if e != nil {
			return nil, e
		}
		defer f.Close()
		b, e := io.ReadAll(io.LimitReader(f, c.Size+1))
		if e != nil {
			return nil, e
		}
		return verified(c, b)
	}
}
func FromDirectory(root string) Source { return directory(root) }
func fromArchive(r io.ReaderAt, n int64) (Source, error) {
	// Check central-directory bounds before archive/zip indexes any untrusted names.
	tail := make([]byte, min(n, 65557))
	if _, e := r.ReadAt(tail, n-int64(len(tail))); e != nil {
		return nil, e
	}
	pos := bytes.LastIndex(tail, []byte{'P', 'K', 5, 6})
	if pos < 0 || len(tail)-pos < 22 {
		return nil, ErrFormat
	}
	d := tail[pos:]
	u := binary.LittleEndian
	if u.Uint16(d[4:]) != 0 || u.Uint16(d[6:]) != 0 || u.Uint16(d[10:]) > 256 || u.Uint32(d[12:]) > 256*1024 || int(u.Uint16(d[20:])) != len(d)-22 {
		return nil, ErrFormat
	}
	if u.Uint16(d[8:]) != u.Uint16(d[10:]) || int64(u.Uint32(d[16:]))+int64(u.Uint32(d[12:])) != n-int64(len(tail))+int64(pos) {
		return nil, ErrFormat
	}
	central := make([]byte, u.Uint32(d[12:]))
	if _, e := r.ReadAt(central, int64(u.Uint32(d[16:]))); e != nil {
		return nil, e
	}
	entries := 0
	for len(central) > 0 {
		if len(central) < 46 || u.Uint32(central) != 0x02014b50 || entries >= 256 {
			return nil, ErrFormat
		}
		step := 46 + int(u.Uint16(central[28:])) + int(u.Uint16(central[30:])) + int(u.Uint16(central[32:]))
		if step > len(central) {
			return nil, ErrFormat
		}
		central = central[step:]
		entries++
	}
	if entries != int(u.Uint16(d[10:])) {
		return nil, ErrFormat
	}
	z, e := zip.NewReader(r, n)
	if e != nil {
		return nil, e
	}
	desired := map[string]bool{}
	for _, c := range Board.Files {
		desired[c.Path] = true
	}
	found := map[string]*zip.File{}
	for _, f := range z.File {
		name := strings.TrimPrefix(f.Name, "vendor/")
		if !desired[name] {
			continue
		}
		if found[name] != nil {
			return nil, ErrFormat
		}
		found[name] = f
	}
	return func(c Component) ([]byte, error) {
		f := found[c.Path]
		if f == nil || f.UncompressedSize64 != uint64(c.Size) {
			return nil, fmt.Errorf("%w: %s", ErrMismatch, c.Path)
		}
		h, e := f.Open()
		if e != nil {
			return nil, e
		}
		defer h.Close()
		b, e := io.ReadAll(io.LimitReader(h, c.Size+1))
		if e != nil {
			return nil, e
		}
		return verified(c, b)
	}, nil
}

type piece struct {
	start, end, at int64
	kind           uint16
	fill           [4]byte
}
type sparse struct {
	r      io.ReaderAt
	pieces []piece
}

func sparseReader(r io.ReaderAt, n int64) (io.ReaderAt, error) {
	var h [28]byte
	if _, e := r.ReadAt(h[:], 0); e != nil {
		return nil, e
	}
	u := binary.LittleEndian
	fileHeader := int64(u.Uint16(h[8:]))
	chunkHeader := int64(u.Uint16(h[10:]))
	block := int64(u.Uint32(h[12:]))
	count := u.Uint32(h[20:])
	if u.Uint16(h[4:]) != 1 || fileHeader < 28 || fileHeader > 4096 || chunkHeader < 12 || chunkHeader > 4096 || block <= 0 || block > 1<<20 || block*int64(u.Uint32(h[16:])) != Board.RawSize || count > 65536 {
		return nil, ErrFormat
	}
	s := &sparse{r: r}
	off := fileHeader
	var logical int64
	for i := uint32(0); i < count; i++ {
		var head [12]byte
		if _, e := r.ReadAt(head[:], off); e != nil {
			return nil, e
		}
		size := int64(u.Uint32(head[4:])) * block
		total := int64(u.Uint32(head[8:]))
		kind := u.Uint16(head[:])
		if total < chunkHeader || off > n-total || size > Board.RawSize-logical {
			return nil, ErrFormat
		}
		payload := total - chunkHeader
		p := piece{start: logical, end: logical + size, at: off + chunkHeader, kind: kind}
		switch kind {
		case 0xcac1:
			if payload != size {
				return nil, ErrFormat
			}
		case 0xcac2:
			if payload != 4 {
				return nil, ErrFormat
			}
			if _, e := r.ReadAt(p.fill[:], p.at); e != nil {
				return nil, e
			}
		case 0xcac3:
			if payload != 0 {
				return nil, ErrFormat
			}
		case 0xcac4:
			if size != 0 || payload != 4 {
				return nil, ErrFormat
			}
		default:
			return nil, ErrFormat
		}
		if size > 0 {
			s.pieces = append(s.pieces, p)
		}
		logical += size
		off += total
	}
	if logical != Board.RawSize || off != n {
		return nil, ErrFormat
	}
	return s, nil
}
func (s *sparse) ReadAt(buf []byte, off int64) (int, error) {
	done := 0
	for _, p := range s.pieces {
		if off < p.start || off >= p.end {
			continue
		}
		count := int(min(int64(len(buf)-done), p.end-off))
		a := buf[done : done+count]
		switch p.kind {
		case 0xcac1:
			if _, e := s.r.ReadAt(a, p.at+off-p.start); e != nil {
				return done, e
			}
		case 0xcac2:
			for i := range a {
				a[i] = p.fill[(off-p.start+int64(i))%4]
			}
		case 0xcac3:
			clear(a)
		}
		off += int64(count)
		done += count
		if done == len(buf) {
			return done, nil
		}
	}
	return done, io.EOF
}
func FromFile(r io.ReaderAt, n int64) (Source, error) {
	if n < 28 {
		return nil, ErrFormat
	}
	var h [4]byte
	if _, e := r.ReadAt(h[:], 0); e != nil {
		return nil, e
	}
	switch {
	case h == [4]byte{'P', 'K', 3, 4}:
		return fromArchive(r, n)
	case binary.LittleEndian.Uint32(h[:]) == 0xed26ff3a:
		converted, e := sparseReader(r, n)
		if e != nil {
			return nil, e
		}
		r = converted
	case n == Board.RawSize:
	default:
		return nil, ErrFormat
	}
	return func(c Component) ([]byte, error) {
		b := make([]byte, 0, c.Size)
		for _, p := range c.Source {
			chunk := make([]byte, p[1])
			if _, e := r.ReadAt(chunk, p[0]); e != nil {
				return nil, e
			}
			b = append(b, chunk...)
		}
		return verified(c, b)
	}, nil
}
func SavePack(src Source, w io.Writer) error {
	z := zip.NewWriter(w)
	for _, c := range Board.Files {
		b, e := src(c)
		if e != nil {
			return e
		}
		f, e := z.CreateHeader(&zip.FileHeader{Name: c.Path, Method: zip.Store})
		if e != nil {
			return e
		}
		if _, e = f.Write(b); e != nil {
			return e
		}
	}
	return z.Close()
}
