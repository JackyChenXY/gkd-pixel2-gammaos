// SPDX-License-Identifier: Apache-2.0
package slot

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"sort"

	"pixel2/gpu/profile"
)

// The Android misc vendor-bootloader area spans 2–16 KiB. Keep the BCB and wipe package untouched.
const Offset int64 = 8 << 10
const (
	Blank        uint32 = 0x20
	Ready        uint32 = 0x21
	Trial        uint32 = 0x22
	Kept         uint32 = 0x23
	TrialBooting uint32 = 0x24
	KeptBooting  uint32 = 0x25
	Invalid      uint32 = 0xffffffff
)

var ErrSlot = errors.New("driver slot integrity check failed")
var ErrState = errors.New("operation not available in the current boot profile")

func Sector(s uint32) []byte {
	a := make([]byte, 512)
	copy(a, "P2G2")
	binary.LittleEndian.PutUint32(a[4:], 0x00030201)
	binary.LittleEndian.PutUint32(a[8:], s)
	binary.LittleEndian.PutUint32(a[12:], ^s)
	return a
}
func Read(f *os.File) (uint32, error) {
	var b [512]byte
	if _, e := f.ReadAt(b[:], Offset); e != nil {
		return Invalid, e
	}
	s := binary.LittleEndian.Uint32(b[8:])
	if s < Blank || s > KeptBooting || !bytes.Equal(b[:], Sector(s)) {
		return Invalid, nil
	}
	return s, nil
}
func Set(f *os.File, s uint32) error {
	if _, e := f.WriteAt(Sector(s), Offset); e != nil {
		return e
	}
	if e := f.Sync(); e != nil {
		return e
	}
	actual, e := Read(f)
	if e != nil {
		return e
	}
	if actual != s {
		return ErrSlot
	}
	return nil
}
func digest(r io.Reader) (string, error) {
	h := sha256.New()
	if _, e := io.Copy(h, r); e != nil {
		return "", e
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
func full(f *os.File) error {
	h, e := digest(io.NewSectionReader(f, 0, profile.Board.SlotSize))
	if e != nil {
		return e
	}
	if h != profile.Board.FullHash {
		return ErrSlot
	}
	return nil
}
func base(f *os.File) error {
	var spans [][2]int64
	for _, c := range profile.Board.Files {
		spans = append(spans, c.Dest...)
	}
	sort.Slice(spans, func(i, j int) bool { return spans[i][0] < spans[j][0] })
	h := sha256.New()
	off := int64(0)
	zeros := make([]byte, 64<<10)
	for _, s := range spans {
		if _, e := io.Copy(h, io.NewSectionReader(f, off, s[0]-off)); e != nil {
			return e
		}
		for n := s[1]; n > 0; {
			k := min(n, int64(len(zeros)))
			h.Write(zeros[:k])
			n -= k
		}
		off = s[0] + s[1]
	}
	if _, e := io.Copy(h, io.NewSectionReader(f, off, profile.Board.SlotSize-off)); e != nil {
		return e
	}
	if hex.EncodeToString(h.Sum(nil)) != profile.Board.EmptyHash {
		return ErrSlot
	}
	return nil
}
func Installed(s uint32) bool { return s >= Ready && s <= KeptBooting }
func Install(control, vendor *os.File, active string, source profile.Source) error {
	if active != "mesa" && active != "forced" {
		return ErrState
	}
	// Validate the entire input and the unchanged portion of the target before invalidating a good installation.
	data := make([][]byte, len(profile.Board.Files))
	for i, c := range profile.Board.Files {
		b, e := source(c)
		if e != nil {
			return e
		}
		sum := sha256.Sum256(b)
		if int64(len(b)) != c.Size || hex.EncodeToString(sum[:]) != c.Hash {
			return profile.ErrMismatch
		}
		data[i] = b
	}
	if e := base(vendor); e != nil {
		return e
	}
	if e := Set(control, Blank); e != nil {
		return e
	}
	for i, c := range profile.Board.Files {
		var index int64
		for _, s := range c.Dest {
			if _, e := vendor.WriteAt(data[i][index:index+s[1]], s[0]); e != nil {
				return e
			}
			index += s[1]
		}
	}
	if e := vendor.Sync(); e != nil {
		return e
	}
	if e := full(vendor); e != nil {
		return e
	}
	return Set(control, Ready)
}
func Action(control, vendor *os.File, active string, op byte) error {
	s, e := Read(control)
	if e != nil {
		return e
	}
	switch op {
	case 'T':
		if active != "mesa" || !Installed(s) {
			return ErrState
		}
		if e = full(vendor); e != nil {
			return e
		}
		return Set(control, Trial)
	case 'M':
		if !Installed(s) {
			return ErrState
		}
		return Set(control, Ready)
	case 'K':
		if active != "trial" || s != TrialBooting {
			return ErrState
		}
		return Set(control, Kept)
	case 'A':
		if active == "kept" && s == KeptBooting {
			return Set(control, Kept)
		}
		return nil
	default:
		return fmt.Errorf("unknown action")
	}
}
