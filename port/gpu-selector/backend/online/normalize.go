// SPDX-License-Identifier: Apache-2.0
package online

import (
	"bytes"
	"debug/elf"
	"encoding/binary"
	"errors"
)

// The SDK strips the last .gnu_debuglink from this already-stripped ARM32 prebuilt.
// Keep the loadable code and data verbatim; rebuild only the section-name table and its index.
func installedMali(input []byte) ([]byte, error) {
	invalid := errors.New("上游 Mali 库与 rc.2 所用的 ELF 格式不符")
	if !matches(input, driver.size, driver.digest) {
		return nil, invalid
	}
	obj, err := elf.NewFile(bytes.NewReader(input))
	if err != nil || obj.Class != elf.ELFCLASS32 || obj.Machine != elf.EM_ARM || obj.Data != elf.ELFDATA2LSB {
		return nil, invalid
	}
	le := binary.LittleEndian
	table := int(le.Uint32(input[32:36]))
	width := int(le.Uint16(input[46:48]))
	count := len(obj.Sections)
	nameIndex := int(le.Uint16(input[50:52]))
	if width != 40 || count < 3 || nameIndex != count-2 || table+width*count != len(input) {
		return nil, invalid
	}
	names, debug := obj.Sections[nameIndex], obj.Sections[count-1]
	if names.Name != ".shstrtab" || debug.Name != ".gnu_debuglink" || debug.Flags&elf.SHF_ALLOC != 0 ||
		names.Offset+names.Size > debug.Offset || debug.Offset+debug.Size > uint64(table) {
		return nil, invalid
	}
	nameOffset := int(names.Offset)
	oldNames := input[nameOffset : nameOffset+int(names.Size)]
	removed := []byte(".gnu_debuglink\x00")
	start := int(le.Uint32(input[table+width*(count-1):]))
	end := start + len(removed)
	if start < 1 || end > len(oldNames) || oldNames[start-1] != 0 || !bytes.Equal(oldNames[start:end], removed) {
		return nil, invalid
	}
	length := len(oldNames) - len(removed)
	newTable := (nameOffset + length + 3) &^ 3
	out := make([]byte, newTable+width*(count-1))
	copy(out, input[:nameOffset+start])
	copy(out[nameOffset+start:], oldNames[end:])
	copy(out[newTable:], input[table:table+width*(count-1)])
	le.PutUint32(out[32:36], uint32(newTable))
	le.PutUint16(out[48:50], uint16(count-1))
	for i := 0; i < count-1; i++ {
		sh := out[newTable+i*width:]
		index := int(le.Uint32(sh))
		if index >= end {
			le.PutUint32(sh, uint32(index-len(removed)))
		} else if index >= start {
			return nil, invalid
		}
	}
	le.PutUint32(out[newTable+nameIndex*width+20:], uint32(length))
	if !matches(out, 27984060, "2749fb338702b3f9a1ebdc7b9e790bb685aba2949b5892343664dbc75f1699b7") {
		return nil, invalid
	}
	return out, nil
}
