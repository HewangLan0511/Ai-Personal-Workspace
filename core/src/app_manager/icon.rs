//! 图标缓存的读取（core 侧）。
//!
//! 分工：图标的**提取**在 Python sidecar（注册表 / 文件属性属"系统 API"，02 §2.4 归 Python；
//! 05 禁止事项也要求不在 UI 线程做这类重活）。core 这里只做一件小事：
//! 把缓存目录里的 PNG 读出来转成 data URL 交给前端。
//!
//! **为什么必须转 data URL**：Tauri webview 不能把本地文件路径直接当 `<img src>` 使用
//! （要走 asset 协议并显式配置 scope）。转 data URL 零配置、且不需要给 webview 开放文件系统。
//!
//! **安全**：本接口只允许读 `icons_dir` **内部**的文件。
//! 否则前端只要传 `C:/Windows/System32/config/SAM` 就能读任意文件 —— 等于任意文件读取漏洞。

use std::path::Path;

/// 读图标缓存文件并转成 `data:image/png;base64,...`。
pub fn read_as_data_url(icons_dir: &Path, icon_path: &str) -> anyhow::Result<String> {
    // 缓存目录必须已存在（未提取过图标时不存在 —— 属正常情况，报可读错误即可）
    let base = icons_dir
        .canonicalize()
        .map_err(|_| anyhow::anyhow!("图标缓存目录尚不存在"))?;

    // canonicalize 会解析 `..` 与符号链接，是对抗目录穿越的正确做法
    let target = Path::new(icon_path)
        .canonicalize()
        .map_err(|_| anyhow::anyhow!("图标文件不存在：{icon_path}"))?;

    if !target.starts_with(&base) {
        anyhow::bail!("拒绝访问图标缓存目录之外的文件：{icon_path}");
    }
    if !target.is_file() {
        anyhow::bail!("不是文件：{icon_path}");
    }

    let bytes = std::fs::read(&target)?;
    if bytes.len() > 4 * 1024 * 1024 {
        anyhow::bail!("图标文件异常偏大（>4MB），拒绝加载");
    }
    Ok(format!("data:image/png;base64,{}", base64(&bytes)))
}

/// 最小 base64 编码（标准表 + `=` 填充）。
///
/// 不引 `base64` crate：项目禁止"需要联网才能运行的依赖"，而这里只有 20 行。
fn base64(data: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for chunk in data.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = *chunk.get(1).unwrap_or(&0) as u32;
        let b2 = *chunk.get(2).unwrap_or(&0) as u32;
        let n = (b0 << 16) | (b1 << 8) | b2;
        out.push(TABLE[(n >> 18) as usize & 63] as char);
        out.push(TABLE[(n >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 {
            TABLE[(n >> 6) as usize & 63] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            TABLE[n as usize & 63] as char
        } else {
            '='
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base64_matches_reference_vectors() {
        // RFC 4648 的经典测试向量
        assert_eq!(base64(b""), "");
        assert_eq!(base64(b"f"), "Zg==");
        assert_eq!(base64(b"fo"), "Zm8=");
        assert_eq!(base64(b"foo"), "Zm9v");
        assert_eq!(base64(b"foob"), "Zm9vYg==");
        assert_eq!(base64(b"fooba"), "Zm9vYmE=");
        assert_eq!(base64(b"foobar"), "Zm9vYmFy");
    }

    /// 目录穿越必须被拒绝 —— 这是本模块唯一的安全边界。
    #[test]
    fn rejects_path_outside_icons_dir() {
        let dir = std::env::temp_dir().join(format!("pw-icon-test-{}", std::process::id()));
        let icons = dir.join("icons");
        std::fs::create_dir_all(&icons).unwrap();
        // 缓存目录之外放一个"敏感文件"
        let outside = dir.join("secret.txt");
        std::fs::write(&outside, b"top-secret").unwrap();

        let err = read_as_data_url(&icons, &outside.to_string_lossy()).unwrap_err();
        assert!(
            err.to_string().contains("拒绝访问"),
            "应拒绝目录外文件，实际：{err}"
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 缓存目录内的 PNG 应能正常读出 data URL。
    #[test]
    fn reads_png_inside_icons_dir() {
        let dir = std::env::temp_dir().join(format!("pw-icon-ok-{}", std::process::id()));
        let icons = dir.join("icons");
        std::fs::create_dir_all(&icons).unwrap();
        let png = icons.join("a.png");
        std::fs::write(&png, b"\x89PNG").unwrap();

        let url = read_as_data_url(&icons, &png.to_string_lossy()).unwrap();
        assert!(url.starts_with("data:image/png;base64,"));

        let _ = std::fs::remove_dir_all(&dir);
    }
}
