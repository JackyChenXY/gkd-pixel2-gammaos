// SPDX-License-Identifier: Apache-2.0
package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"pixel2/gpu/card"
)

func TestLocalImagerEntry(t *testing.T) {
	dir := t.TempDir()
	if external := os.Getenv("PIXEL2_TEST_MANIFEST_DIR"); external != "" {
		dir = external
	}
	path := filepath.Join(dir, "测试 #1.img")
	f, err := manifest(path, card.Current())
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(f)
	if err != nil {
		t.Fatal(err)
	}
	var m struct {
		OS []map[string]any `json:"os_list"`
	}
	if err = json.Unmarshal(b, &m); err != nil || len(m.OS) != 1 {
		t.Fatal("invalid manifest", err)
	}
	entry := m.OS[0]
	s, _ := entry["url"].(string)
	if !strings.HasPrefix(s, "file:///") || !strings.Contains(s, "%23") || !strings.Contains(s, "%E6%B5%8B") || entry["icon"] == nil || entry["release_date"] == nil || entry["extract_sha256"] != card.Current().MaliSHA256 {
		t.Fatal(entry)
	}
}
