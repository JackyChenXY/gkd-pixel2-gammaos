// SPDX-License-Identifier: Apache-2.0
package card

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
)

const oemStart = 214958080

//go:embed oem.json
var oemLayout []byte

type oemFile struct {
	Path, Entry, Hash string
	Size              int64
	Dest              [][2]int64
}

type oemProfile struct {
	Size        int64
	Directories []struct {
		Offset        int64
		Before, After string
	}
	Files []oemFile
}

func matchFile(data []byte, file oemFile) bool {
	sum := sha256.Sum256(data)
	return int64(len(data)) == file.Size && hex.EncodeToString(sum[:]) == file.Hash
}

// The package is verified before any ZIP entry is parsed. Only the two
// expected members are read. Their sizes, hashes and destination bounds
// are checked separately from the final disk hash.
func desktopChanges(apk []byte) ([]change, error) {
	var board oemProfile
	if err := json.Unmarshal(oemLayout, &board); err != nil {
		return nil, err
	}
	if len(board.Files) != 3 || board.Files[0].Entry != "" || !matchFile(apk, board.Files[0]) {
		return nil, fmt.Errorf("AT4K 安装包不是受支持的 H700 版本")
	}
	pkg, err := zip.NewReader(bytes.NewReader(apk), int64(len(apk)))
	if err != nil {
		return nil, err
	}
	var edits []change
	for _, d := range board.Directories {
		if d.Offset < 0 || len(d.Before) != len(d.After) || d.Offset+int64(len(d.After)) > board.Size {
			return nil, fmt.Errorf("invalid OEM directory entry")
		}
		edits = append(edits, change{oemStart + d.Offset, []byte(d.Before), []byte(d.After)})
	}
	for _, file := range board.Files {
		data := apk
		if file.Entry != "" {
			f, err := pkg.Open(file.Entry)
			if err != nil {
				return nil, err
			}
			data, err = io.ReadAll(io.LimitReader(f, file.Size+1))
			f.Close()
			if err != nil {
				return nil, err
			}
			if !matchFile(data, file) {
				return nil, fmt.Errorf("AT4K 资源未通过校验：%s", file.Entry)
			}
		}
		var pos int64
		for _, extent := range file.Dest {
			off, n := extent[0], extent[1]
			if off < 0 || n <= 0 || n > board.Size-off || n > file.Size-pos {
				return nil, fmt.Errorf("invalid OEM extent for %s", file.Path)
			}
			edits = append(edits, change{oemStart + off, nil, data[pos : pos+n]})
			pos += n
		}
		if pos != file.Size {
			return nil, fmt.Errorf("incomplete OEM file: %s", file.Path)
		}
	}
	return edits, nil
}
