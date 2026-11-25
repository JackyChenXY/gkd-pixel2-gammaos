// SPDX-License-Identifier: Apache-2.0
package online

import (
	"bytes"
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"testing"
)

type roundTrip func(*http.Request) (*http.Response, error)

func (f roundTrip) RoundTrip(req *http.Request) (*http.Response, error) { return f(req) }
func silent(string)                                                     {}

func TestFetchChecksDataAndTriesTheNextPinnedURL(t *testing.T) {
	payload := []byte("exact")
	bad := map[string][]byte{"wrong checksum": []byte("Exact"), "short": []byte("exa"), "oversized": []byte("exactly")}
	for name, broken := range bad {
		t.Run(name, func(t *testing.T) {
			calls := 0
			client := &http.Client{Transport: roundTrip(func(req *http.Request) (*http.Response, error) {
				calls++
				body := broken
				if req.URL.Host == "second.invalid" {
					body = payload
				}
				if req.Method != "GET" || req.Header.Get("Accept") != "application/vnd.github.raw+json" {
					t.Fatal("unexpected request")
				}
				return &http.Response{StatusCode: 200, ContentLength: -1, Body: io.NopCloser(bytes.NewReader(body)), Request: req}, nil
			})}
			file := asset{label: "fixture", digest: fmt.Sprintf("%x", sha256.Sum256(payload)), size: int64(len(payload)),
				urls: []string{"https://first.invalid/source", "https://second.invalid/source"}}
			out, err := fetch(context.Background(), client, file, silent)
			if err != nil || !bytes.Equal(out, payload) || calls != 2 {
				t.Fatalf("fallback: %q, %v, %d requests", out, err, calls)
			}
		})
	}
}

func TestFailureDoesNotReplaceAnExistingFileOrLeaveAPartialArchive(t *testing.T) {
	dir := t.TempDir()
	dst := filepath.Join(dir, Filename)
	requests := 0
	unavailable := &http.Client{Transport: roundTrip(func(*http.Request) (*http.Response, error) {
		requests++
		return nil, errors.New("offline test")
	})}
	if err := os.WriteFile(dst, []byte("existing data"), 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := create(context.Background(), unavailable, dst, silent); err == nil || requests != 0 {
		t.Fatalf("existing destination: %v; requests %d", err, requests)
	}
	got, err := os.ReadFile(dst)
	if err != nil || string(got) != "existing data" {
		t.Fatal("existing output modified", err)
	}
	if err := os.Remove(dst); err != nil {
		t.Fatal(err)
	}
	if _, err := create(context.Background(), unavailable, dst, silent); err == nil || requests == 0 {
		t.Fatal("expected an offline failure")
	}
	files, err := os.ReadDir(dir)
	if err != nil || len(files) != 0 {
		t.Fatal("partial output", files, err)
	}
}

func TestConcurrentPublishPreservesTheWinner(t *testing.T) {
	dir := t.TempDir()
	dst := filepath.Join(dir, "result")
	src := filepath.Join(dir, "temp")
	for _, p := range []string{src, dst} {
		if err := os.WriteFile(p, []byte(p), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err := publish(src, dst); err == nil {
		t.Fatal("replaced existing file")
	}
	data, err := os.ReadFile(dst)
	if err != nil || string(data) != dst {
		t.Fatal("changed destination", err)
	}
}

func TestPinnedVendorNormalization(t *testing.T) {
	if _, err := installedMali([]byte("wrong driver")); err == nil {
		t.Fatal("unexpected input was accepted")
	}
	path := os.Getenv("PIXEL2_MALI_UPSTREAM")
	if path == "" {
		t.Skip("set PIXEL2_MALI_UPSTREAM to the pinned, locally acquired upstream ELF")
	}
	input, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	out, err := installedMali(input)
	if err != nil || !matches(out, 27984060, "2749fb338702b3f9a1ebdc7b9e790bb685aba2949b5892343664dbc75f1699b7") {
		t.Fatal("unexpected normalized library", err)
	}
}

func TestCompleteReferenceCanBeReusedOffline(t *testing.T) {
	path := os.Getenv("PIXEL2_MALI_ZIP")
	if path == "" {
		t.Skip("set PIXEL2_MALI_ZIP to a locally created reference ZIP")
	}
	client := &http.Client{Transport: roundTrip(func(*http.Request) (*http.Response, error) {
		t.Fatal("valid existing ZIP caused network access")
		return nil, nil
	})}
	hit, err := create(context.Background(), client, path, silent)
	if err != nil || !hit {
		t.Fatal("existing reference was not reused", err)
	}
}
