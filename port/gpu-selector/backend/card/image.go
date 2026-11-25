// SPDX-License-Identifier: Apache-2.0
// Package card builds a new personal TF image using verified inputs and a sequential writer.
package card

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"sort"

	"pixel2/gpu/profile"
	"pixel2/gpu/slot"
)

type Release struct {
	Size         int64
	GzipSize     int64
	PublicSHA256 string
	GzipSHA256   string
	MaliSHA256   string
}

//go:embed release.json
var metadata []byte

func Current() Release {
	var r Release
	if err := json.Unmarshal(metadata, &r); err != nil {
		panic(err)
	}
	return r
}

const ImageName = "GKD-Pixel2-GammaOS.img.gz"
const PersonalName = "GKD-Pixel2-GammaOS-Mali.img"
const control = 319488*512 + slot.Offset
const vendor = 641024 * 512

type change struct {
	offset        int64
	before, after []byte
}

func changes(source profile.Source) ([]change, error) {
	out := []change{{control, slot.Sector(slot.Blank), slot.Sector(slot.Ready)}}
	for _, component := range profile.Board.Files {
		data, err := source(component)
		if err != nil {
			return nil, err
		}
		if int64(len(data)) != component.Size || fmt.Sprintf("%x", sha256.Sum256(data)) != component.Hash {
			return nil, profile.ErrMismatch
		}
		var cursor int64
		for _, extent := range component.Dest {
			start, size := extent[0], extent[1]
			if size <= 0 || start < 0 || size > profile.Board.SlotSize-start || size > component.Size-cursor {
				return nil, fmt.Errorf("invalid extent for %s", component.Path)
			}
			out = append(out, change{vendor + start, nil, data[cursor : cursor+size]})
			cursor += size
		}
		if cursor != component.Size {
			return nil, profile.ErrMismatch
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].offset < out[j].offset })
	return out, nil
}

func convert(input io.Reader, output io.Writer, size int64, patches []change) error {
	var pos int64
	scratch := make([]byte, 128<<10)
	for _, p := range patches {
		if p.offset < pos || p.offset > size-int64(len(p.after)) {
			return fmt.Errorf("driver extent outside image or overlapping")
		}
		if _, err := io.CopyN(output, input, p.offset-pos); err != nil {
			return err
		}
		for i := 0; i < len(p.after); {
			n := min(len(scratch), len(p.after)-i)
			part := scratch[:n]
			if _, err := io.ReadFull(input, part); err != nil {
				return err
			}
			if p.before != nil {
				if len(p.before) != len(p.after) || !bytes.Equal(part, p.before[i:i+n]) {
					return fmt.Errorf("unexpected factory driver selection")
				}
			} else {
				for _, b := range part {
					if b != 0 {
						return fmt.Errorf("driver slot is not empty")
					}
				}
			}
			i += n
		}
		if _, err := io.Copy(output, bytes.NewReader(p.after)); err != nil {
			return err
		}
		pos = p.offset + int64(len(p.after))
	}
	if _, err := io.CopyN(output, input, size-pos); err != nil {
		return err
	}
	var extra [1]byte
	n, err := io.ReadFull(input, extra[:])
	if n != 0 || err != io.EOF {
		return fmt.Errorf("wrong image length or damaged compressed stream: %v", err)
	}
	return nil
}

// Prepare verifies the compressed download, original image and final image, including all unchanged partitions.
func Prepare(input io.Reader, output io.Writer, source profile.Source, release Release) error {
	edits, err := changes(source)
	if err != nil {
		return err
	}
	limited := &io.LimitedReader{R: input, N: release.GzipSize + 1}
	zippedHash := sha256.New()
	raw, err := gzip.NewReader(io.TeeReader(limited, zippedHash))
	if err != nil {
		return err
	}
	defer raw.Close()
	baseHash, finalHash := sha256.New(), sha256.New()
	if err = convert(io.TeeReader(raw, baseHash), io.MultiWriter(output, finalHash), release.Size, edits); err != nil {
		return err
	}
	if limited.N != 1 || hex.EncodeToString(zippedHash.Sum(nil)) != release.GzipSHA256 || hex.EncodeToString(baseHash.Sum(nil)) != release.PublicSHA256 || hex.EncodeToString(finalHash.Sum(nil)) != release.MaliSHA256 {
		return fmt.Errorf("镜像内容与本版公布的 SHA-256 不符")
	}
	return nil
}
