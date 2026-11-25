// SPDX-License-Identifier: Apache-2.0
package card

import (
	"bytes"
	"testing"
)

func TestOnlyDeclaredBytesChange(t *testing.T) {
	in := []byte{1, 2, 0, 0, 5, 6, 7, 8}
	edits := []change{{2, nil, []byte{9, 10}}, {5, []byte{6}, []byte{11}}}
	var out bytes.Buffer
	if err := convert(bytes.NewReader(in), &out, 8, edits); err != nil || !bytes.Equal(out.Bytes(), []byte{1, 2, 9, 10, 5, 11, 7, 8}) {
		t.Fatalf("%x %v", out.Bytes(), err)
	}
	for _, broken := range [][]byte{{1, 2, 1, 0, 5, 6, 7, 8}, {1, 2, 0, 0, 5, 4, 7, 8}, in[:7], append(append([]byte{}, in...), 0)} {
		out.Reset()
		if err := convert(bytes.NewReader(broken), &out, 8, edits); err == nil {
			t.Fatal("accepted damaged or incorrect base")
		}
	}
}
