// SPDX-License-Identifier: Apache-2.0
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strings"

	"pixel2/gpu/card"
	"pixel2/gpu/online"
	"pixel2/gpu/profile"
)

const title = "GammaOS · GKD Pixel 2 安装助手"

func reusable(path string, size int64, digest string) (bool, error) {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if info.Mode().IsRegular() && info.Size() == size {
		f, err := os.Open(path)
		if err != nil {
			return false, err
		}
		defer f.Close()
		sum := sha256.New()
		n, err := io.Copy(sum, f)
		if err != nil {
			return false, err
		}
		if n == size && hex.EncodeToString(sum.Sum(nil)) == digest {
			return true, nil
		}
	}
	return false, fmt.Errorf("此位置已有其他内容，请选择另一个输出文件夹：%s", path)
}

func newImage(ctx context.Context, base, pack, temp, dest string) error {
	r := card.Current()
	say := func(s string) { fmt.Println(s) }
	if pack == "" {
		pack = filepath.Join(temp, online.Filename)
	}
	if _, err := online.Create(ctx, pack, say); err != nil {
		return err
	}
	driver, err := os.Open(pack)
	if err != nil {
		return err
	}
	defer driver.Close()
	src, err := profile.FromFile(driver, online.ResultSize)
	if err != nil {
		return err
	}
	var input io.ReadCloser
	if base != "" {
		input, err = os.Open(base)
	} else {
		say("正在从 GitHub 下载公开镜像并整合驱动。")
		input, err = online.OpenFirmware(ctx, r.GzipSize)
	}
	if err != nil {
		return err
	}
	defer input.Close()
	out, err := os.CreateTemp(temp, "image-*.tmp")
	if err != nil {
		return err
	}
	defer out.Close()
	meter := &progress{ctx: ctx, total: r.GzipSize, next: 10}
	if err = card.Prepare(io.TeeReader(input, meter), out, src, r); err != nil {
		return err
	}
	if err = out.Sync(); err != nil {
		return err
	}
	if err = out.Close(); err != nil {
		return err
	}
	if err = ctx.Err(); err != nil {
		return err
	}
	if err = online.PublishNew(out.Name(), dest); err != nil {
		if ok, e := reusable(dest, r.Size, r.MaliSHA256); ok {
			return nil
		} else if e != nil {
			return e
		}
		return err
	}
	return nil
}

type progress struct {
	ctx              context.Context
	total, got, next int64
}

func (p *progress) Write(b []byte) (int, error) {
	if err := p.ctx.Err(); err != nil {
		return 0, err
	}
	p.got += int64(len(b))
	pct := p.got * 100 / p.total
	if pct >= p.next {
		fmt.Printf("%d%%\n", pct)
		p.next = pct/10*10 + 10
	}
	return len(b), nil
}

func imageURL(path string) string {
	p := filepath.ToSlash(path)
	if strings.HasPrefix(p, "//") {
		host, rest, _ := strings.Cut(p[2:], "/")
		return (&url.URL{Scheme: "file", Host: host, Path: "/" + rest}).String()
	}
	if !strings.HasPrefix(p, "/") {
		p = "/" + p
	}
	return (&url.URL{Scheme: "file", Path: p}).String()
}
func manifest(image string, r card.Release) (string, error) {
	// Use a unique filename. A user may keep several cards or other manifests in this folder.
	f, err := os.CreateTemp(filepath.Dir(image), "Pixel2-*.rpi-imager-manifest")
	if err != nil {
		return "", err
	}
	ok := false
	defer func() {
		f.Close()
		if !ok {
			os.Remove(f.Name())
		}
	}()
	name := "GammaOS · GKD Pixel 2"
	entry := map[string]any{
		"name": name, "description": "Mesa + Mali · Android 12",
		"icon":         "https://raw.githubusercontent.com/JackyChenXY/gkd-pixel2-gammaos/v0.3.0/docs/images/pixel2-boot.png",
		"website":      "https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/tag/v0.3.0",
		"release_date": "2026-11-26", "url": imageURL(image),
		"extract_size": r.Size, "extract_sha256": r.MaliSHA256, "image_download_size": r.Size,
		"devices": []string{"gkd-pixel2"},
	}
	devices := []map[string]any{{"name": "GKD Pixel 2", "description": "GameKiddy Pixel 2 · RK3326S", "tags": []string{"gkd-pixel2"}}}
	data := map[string]any{"imager": map[string]any{"default_os": name, "devices": devices}, "os_list": []any{entry}}
	if err = json.NewEncoder(f).Encode(data); err != nil {
		return "", err
	}
	if err = f.Close(); err != nil {
		return "", err
	}
	ok = true
	return f.Name(), nil
}
func beside(dir, name string) (string, error) {
	p := filepath.Join(dir, name)
	_, err := os.Lstat(p)
	if errors.Is(err, os.ErrNotExist) {
		return "", nil
	}
	return p, err
}
func run() error {
	output := flag.String("out-dir", "", "输出文件夹，默认与安装助手同目录")
	base := flag.String("base", "", "从本地读取本版公开 .img.gz")
	pack := flag.String("pack", "", "从本地读取匹配的驱动 ZIP")
	prepare := flag.Bool("prepare-only", false, "只生成镜像")
	notices := flag.Bool("licenses", false, "显示许可与来源")
	flag.Parse()
	if flag.NArg() != 0 {
		return errors.New("请双击运行或使用 --help 查看参数")
	}
	if *notices {
		return online.Notices(os.Stdout)
	}
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	if *output == "" {
		*output = filepath.Dir(exe)
	}
	dir, err := filepath.Abs(*output)
	if err != nil {
		return err
	}
	r := card.Current()
	image := filepath.Join(dir, card.PersonalName)
	fmt.Println(title, "\n输出位置", image)
	exists, err := reusable(image, r.Size, r.MaliSHA256)
	if err != nil {
		return err
	}
	if !exists {
		if *base == "" {
			*base, err = beside(dir, card.ImageName)
			if err != nil {
				return err
			}
		}
		if *pack == "" {
			*pack, err = beside(dir, online.Filename)
			if err != nil {
				return err
			}
		} else if _, err := os.Stat(*pack); err != nil {
			return err
		}
		temp, err := os.MkdirTemp(dir, ".pixel2-")
		if err != nil {
			return err
		}
		// Only our freshly-created directory contains temporary downloads and this run's output.
		defer os.RemoveAll(temp)
		ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt)
		defer cancel()
		if err = newImage(ctx, *base, *pack, temp, image); err != nil {
			return err
		}
	}
	fmt.Println("双驱动镜像校验通过", image)
	if *prepare {
		return nil
	}
	list, err := manifest(image, r)
	if err != nil {
		return err
	}
	fmt.Println("请在刷卡器中选择目标 TF 卡，核对容量并确认写入。")
	return launchImager(list)
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		if len(os.Args) == 1 {
			displayError(err.Error())
		}
		os.Exit(1)
	}
}
