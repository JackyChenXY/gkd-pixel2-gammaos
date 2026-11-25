// SPDX-License-Identifier: Apache-2.0
package slot

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

func TestAcknowledgement(t *testing.T) {
	f, e := os.Create(filepath.Join(t.TempDir(), "card"))
	if e != nil {
		t.Fatal(e)
	}
	defer f.Close()
	for _, a := range []struct {
		s    uint32
		mode string
		op   byte
		next uint32
		ok   bool
	}{
		{TrialBooting, "trial", 'A', TrialBooting, true}, {TrialBooting, "mesa", 'K', TrialBooting, false},
		{TrialBooting, "trial", 'K', Kept, true}, {KeptBooting, "kept", 'A', Kept, true},
		{Ready, "kept", 'A', Ready, true}, {Kept, "trial", 'M', Ready, true}, {Blank, "mesa", 'T', Blank, false},
	} {
		if e = Set(f, a.s); e != nil {
			t.Fatal(e)
		}
		e = Action(f, nil, a.mode, a.op)
		state, x := Read(f)
		if (e == nil) != a.ok || x != nil || state != a.next {
			t.Errorf("%+v state=%d error=%v", a, state, e)
		}
	}
	invalid := Sector(Trial)
	invalid[12] ^= 1
	f.WriteAt(invalid, Offset)
	state, e := Read(f)
	if state != Invalid || e != nil {
		t.Fatal(state, e)
	}
}
func TestCanonicalRecord(t *testing.T) {
	b := Sector(Trial)
	if !bytes.Equal(b[:16], []byte{0x50, 0x32, 0x47, 0x32, 1, 2, 3, 0, 0x22, 0, 0, 0, 0xdd, 0xff, 0xff, 0xff}) {
		t.Fatal(b[:16])
	}
}

// Android first-stage init marks a mounted vendor block device read-only.
func TestKeepWithReadOnlyMountedVendor(t *testing.T) {
	dir := t.TempDir()
	control, err := os.Create(filepath.Join(dir, "misc"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	path := filepath.Join(dir, "vendor")
	if err := os.WriteFile(path, []byte("mounted graphics data"), 0400); err != nil {
		t.Fatal(err)
	}
	vendor, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer vendor.Close()
	for _, step := range []struct {
		before uint32
		active string
		op     byte
		after  uint32
	}{
		{TrialBooting, "trial", 'K', Kept},
		{KeptBooting, "kept", 'A', Kept},
		{Kept, "kept", 'M', Ready},
	} {
		if err := Set(control, step.before); err != nil {
			t.Fatal(err)
		}
		if err := Action(control, vendor, step.active, step.op); err != nil {
			t.Fatal(err)
		}
		got, err := Read(control)
		if err != nil || got != step.after {
			t.Fatalf("state %d, error %v", got, err)
		}
	}
	b, err := os.ReadFile(path)
	if err != nil || string(b) != "mounted graphics data" {
		t.Fatal("read-only vendor changed", err)
	}
}
