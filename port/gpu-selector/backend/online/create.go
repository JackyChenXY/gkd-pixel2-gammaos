// SPDX-License-Identifier: Apache-2.0
package online

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"os"
	"path/filepath"

	"pixel2/gpu/profile"
)

const Filename = "Pixel2-Mali.local.zip"
const ResultSHA256 = "9bb7a89a1d6875df1c1a25c74baed814f5b959099883c8beb5204dec5bbdc686"
const ResultSize = 28716111
const supportPath = "bundle/Pixel2-Mali-Support.zip"

// The release build puts the audited support archive beside the source-controlled notice.
// A plain source build can retrieve the very same archive from the public tool release.
//
//go:embed bundle/*
var bundled embed.FS

func supportBytes(ctx context.Context, client *http.Client, say func(string)) ([]byte, error) {
	data, err := bundled.ReadFile(supportPath)
	if errors.Is(err, fs.ErrNotExist) {
		return fetch(ctx, client, support, say)
	}
	if err != nil {
		return nil, err
	}
	if !matches(data, support.size, support.digest) {
		return nil, errors.New("工具内置的配套文件校验失败，请重新下载发布版工具")
	}
	return data, nil
}

func Notices(w io.Writer) error {
	body, err := bundled.ReadFile("bundle/NOTICE.txt")
	if err != nil {
		return err
	}
	if _, err := w.Write(body); err != nil {
		return err
	}
	b, err := bundled.ReadFile(supportPath)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	z, err := zip.NewReader(bytes.NewReader(b), int64(len(b)))
	if err != nil {
		return err
	}
	f, err := z.Open("NOTICE.txt")
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = io.Copy(w, f)
	return err
}

func existing(path string) (bool, error) {
	info, err := os.Lstat(path)
	if errors.Is(err, fs.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if info.Mode().IsRegular() && info.Size() == ResultSize {
		f, err := os.Open(path)
		if err != nil {
			return false, err
		}
		defer f.Close()
		h := sha256.New()
		n, err := io.Copy(h, io.LimitReader(f, ResultSize+1))
		if err != nil {
			return false, err
		}
		if n == ResultSize && hex.EncodeToString(h.Sum(nil)) == ResultSHA256 {
			return true, nil
		}
	}
	return false, fmt.Errorf("此位置已有其他文件，请移走同名文件或选择新的输出路径：%s", path)
}

func writePackage(ctx context.Context, client *http.Client, dst io.Writer, say func(string)) error {
	data, err := supportBytes(ctx, client, say)
	if err != nil {
		return err
	}
	companion, err := profile.FromFile(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return err
	}

	configA, err := fetch(ctx, client, allocator, say)
	if err != nil {
		return err
	}
	configC, err := fetch(ctx, client, composer, say)
	if err != nil {
		return err
	}
	raw, err := fetch(ctx, client, driver, say)
	if err != nil {
		return err
	}
	gles, err := installedMali(raw)
	if err != nil {
		return err
	}

	say("正在校验 11 个文件并生成驱动包")
	return profile.SavePack(func(c profile.Component) ([]byte, error) {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		switch c.Path {
		case allocatorPath:
			return configA, nil
		case composerPath:
			return configC, nil
		case driverPath:
			return gles, nil
		default:
			return companion(c)
		}
	}, dst)
}

// Create leaves a complete reference ZIP at path. An identical existing file needs no network.
func Create(ctx context.Context, path string, say func(string)) (already bool, err error) {
	return create(ctx, webClient(), path, say)
}

func create(ctx context.Context, client *http.Client, path string, say func(string)) (bool, error) {
	if same, err := existing(path); same || err != nil {
		return same, err
	}
	temp, err := os.CreateTemp(filepath.Dir(path), ".pixel2-mali-*.tmp")
	if err != nil {
		return false, fmt.Errorf("无法在所选文件夹创建文件：%w", err)
	}
	defer func() { temp.Close(); os.Remove(temp.Name()) }()
	hash := sha256.New()
	if err := writePackage(ctx, client, io.MultiWriter(temp, hash), say); err != nil {
		return false, err
	}
	stat, err := temp.Stat()
	if err != nil {
		return false, err
	}
	if stat.Size() != ResultSize || hex.EncodeToString(hash.Sum(nil)) != ResultSHA256 {
		return false, errors.New("整包校验与 本版参考值不符")
	}
	if err := temp.Sync(); err != nil {
		return false, err
	}
	if err := temp.Close(); err != nil {
		return false, err
	}
	if err := ctx.Err(); err != nil {
		return false, err
	}
	if err := publish(temp.Name(), path); err != nil {
		if same, otherErr := existing(path); same || otherErr != nil {
			return same, otherErr
		}
		return false, err
	}
	return false, nil
}
