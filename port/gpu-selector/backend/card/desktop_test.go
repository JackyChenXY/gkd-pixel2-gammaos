// SPDX-License-Identifier: Apache-2.0
package card

import (
	"os"
	"testing"
)

func TestSignedDesktopInputs(t *testing.T) {
	if _, err := desktopChanges([]byte("invalid APK")); err == nil {
		t.Fatal("accepted wrong APK")
	}
	path := os.Getenv("PIXEL2_AT4K_APK")
	if path == "" {
		return
	}
	apk, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	edits, err := desktopChanges(apk)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range edits {
		if e.offset < oemStart || e.offset+int64(len(e.after)) > oemStart+(32<<20) {
			t.Fatal("desktop edit outside its OEM partition")
		}
	}
	apk[len(apk)/2] ^= 1
	if _, err := desktopChanges(apk); err == nil {
		t.Fatal("accepted altered APK")
	}
}
