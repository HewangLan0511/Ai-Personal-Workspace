//! 布局计算：**归一化坐标 → 像素**。
//!
//! 本模块是全阶段唯一要求"**纯函数、可脱离系统单测**"的部分（07 §工程要求 + 验收项 10）——
//! 故这里不碰任何 Win32 API，输入输出都是普通数据，测试不需要真实显示器。
//!
//! ## 为什么用归一化坐标（07 §禁止事项）
//! 像素写死在布局文件里，换显示器 / 改分辨率 / 改 DPI 缩放就会全崩。
//! 归一化坐标 + 运行时按**目标显示器工作区**换算，才能自适应。
//!
//! ## DPI 怎么办（验收项 8）
//! 应用在启动时声明 `PER_MONITOR_AWARE_V2`（见 `monitor.rs`），此后 Win32 返回的
//! work area 就是**物理像素**，与布局计算同一坐标系 —— 所以本模块**不需要**再做缩放换算。
//! 若漏掉 DPI 声明，系统会返回"虚拟化"坐标，高分屏上比例必错。这不是本模块能补的。

use serde::{Deserialize, Serialize};

/// 归一化矩形（各分量 0~1，相对于目标显示器工作区）。
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

/// 像素矩形。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PxRect {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

/// 显示器工作区（像素，**不含任务栏**）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkArea {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

/// AI 侧栏（契约 3.2.2 的 `aiSidebar`）。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AiSidebar {
    #[serde(default)]
    pub enabled: bool,
    /// `"left"` / `"right"`；缺省按 `right`
    #[serde(default)]
    pub edge: String,
    /// 占工作区宽度的比例（0~1）
    #[serde(default)]
    pub width: f64,
}

/// 把一个归一化槽位换算成像素矩形（**纯函数**）。
///
/// 规则（07 §4）：
/// 1. 以显示器工作区为基准（不含任务栏）；
/// 2. 侧栏启用时**先扣掉侧栏宽度**，再在剩余宽度上做归一化映射 ——
///    这样"窗口不覆盖 AI 区域"是**算出来的**，不是靠事后裁剪；
/// 3. 侧栏在左则整体右移，在右则宽度直接减掉。
pub fn to_pixels(slot: &Rect, work: WorkArea, sidebar: Option<&AiSidebar>) -> PxRect {
    let (usable_x, usable_w) = usable_box(work, sidebar);

    let px = usable_x + (slot.x * usable_w as f64).round() as i32;
    let py = work.y + (slot.y * work.h as f64).round() as i32;
    let pw = (slot.w * usable_w as f64).round() as i32;
    let ph = (slot.h * work.h as f64).round() as i32;

    PxRect { x: px, y: py, w: pw, h: ph }
}

/// 扣掉 AI 侧栏后，留给窗口的可用区域（像素）。
pub fn usable_box(work: WorkArea, sidebar: Option<&AiSidebar>) -> (i32, i32) {
    match sidebar {
        Some(sb) if sb.enabled && sb.width > 0.0 => {
            // 夹到 [0, 1]，避免布局文件写错导致可用宽度为负
            let ratio = sb.width.clamp(0.0, 1.0);
            let sb_w = (work.w as f64 * ratio).round() as i32;
            if sb.edge.eq_ignore_ascii_case("left") {
                (work.x + sb_w, work.w - sb_w)
            } else {
                (work.x, work.w - sb_w)
            }
        }
        _ => (work.x, work.w),
    }
}

/// 整块布局的像素结果（应用前先全算出来，便于"先校验后执行"）。
pub fn layout_pixels(slots: &[Rect], work: WorkArea, sidebar: Option<&AiSidebar>) -> Vec<PxRect> {
    slots.iter().map(|s| to_pixels(s, work, sidebar)).collect()
}

/// 两个像素矩形是否重叠（验收项 3「无重叠」的判据）。
///
/// 生产路径暂未调用（`verify_stage3.py` 在外部用同一判据校验），
/// 但单元测试直接用它断言四宫格互不重叠 —— 故保留为公开 API。
#[allow(dead_code)]
pub fn overlaps(a: &PxRect, b: &PxRect) -> bool {
    // 相邻不算重叠：用严格小于，边贴边（a.x+a.w == b.x）视为不重叠
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
}

#[cfg(test)]
mod tests {
    use super::*;

    fn work(w: i32, h: i32) -> WorkArea {
        WorkArea { x: 0, y: 0, w, h }
    }

    /// 基础换算：1920×1080 四宫格应精确切成四块 960×540。
    #[test]
    fn quad_splits_evenly() {
        let quad = [
            Rect { x: 0.0, y: 0.0, w: 0.5, h: 0.5 },
            Rect { x: 0.5, y: 0.0, w: 0.5, h: 0.5 },
            Rect { x: 0.0, y: 0.5, w: 0.5, h: 0.5 },
            Rect { x: 0.5, y: 0.5, w: 0.5, h: 0.5 },
        ];
        let px = layout_pixels(&quad, work(1920, 1080), None);
        assert_eq!(px[0], PxRect { x: 0, y: 0, w: 960, h: 540 });
        assert_eq!(px[1], PxRect { x: 960, y: 0, w: 960, h: 540 });
        assert_eq!(px[2], PxRect { x: 0, y: 540, w: 960, h: 540 });
        assert_eq!(px[3], PxRect { x: 960, y: 540, w: 960, h: 540 });

        // 验收项 3：四宫格无重叠，且铺满整屏
        for i in 0..4 {
            for j in (i + 1)..4 {
                assert!(!overlaps(&px[i], &px[j]), "槽位 {i} 与 {j} 重叠");
            }
        }
        let area: i64 = px.iter().map(|r| r.w as i64 * r.h as i64).sum();
        assert_eq!(area, 1920 * 1080, "四宫格应铺满工作区");
    }

    /// 验收项 6：启用右侧 AI 侧栏后，窗口**不得覆盖**右侧区域。
    #[test]
    fn sidebar_reserves_right_band() {
        let work = work(1920, 1080);
        let sb = AiSidebar { enabled: true, edge: "right".into(), width: 0.2 };
        let (usable_x, usable_w) = usable_box(work, Some(&sb));
        assert_eq!((usable_x, usable_w), (0, 1536), "右侧留出 20% 给侧栏");

        // 占满整宽的槽位，右边界必须停在 1536，而不是 1920
        let full = Rect { x: 0.0, y: 0.0, w: 1.0, h: 1.0 };
        let px = to_pixels(&full, work, Some(&sb));
        assert_eq!(px.x + px.w, 1536, "窗口右边界不得侵入侧栏");
    }

    /// 侧栏在左时，整体右移。
    #[test]
    fn sidebar_on_left_shifts_windows() {
        let work = work(1000, 800);
        let sb = AiSidebar { enabled: true, edge: "left".into(), width: 0.25 };
        let (usable_x, usable_w) = usable_box(work, Some(&sb));
        assert_eq!((usable_x, usable_w), (250, 750));

        let full = Rect { x: 0.0, y: 0.0, w: 1.0, h: 1.0 };
        let px = to_pixels(&full, work, Some(&sb));
        assert_eq!(px.x, 250);
        assert_eq!(px.x + px.w, 1000);
    }

    /// 验收项 7：第二显示器有非零原点 —— 换算必须带上工作区偏移，不能从 0 开始。
    #[test]
    fn second_monitor_keeps_origin_offset() {
        // 假设主屏 2560 宽，副屏在其右侧（x=2560），高度小一些
        let second = WorkArea { x: 2560, y: -100, w: 1920, h: 1080 };
        let half = Rect { x: 0.5, y: 0.0, w: 0.5, h: 1.0 };
        let px = to_pixels(&half, second, None);
        assert_eq!(px, PxRect { x: 2560 + 960, y: -100, w: 960, h: 1080 });
    }

    /// 验收项 8：DPI 感知开启后 work area 是**物理像素**，比例应与 100% 缩放一致。
    /// （本模块不做缩放换算 —— 这里用同一逻辑跑 125%/150% 的物理尺寸，验证比例不变。）
    #[test]
    fn dpi_scale_keeps_ratio() {
        let slot = Rect { x: 0.0, y: 0.0, w: 0.5, h: 0.5 };
        // 100%：1920×1080 逻辑 = 物理
        let s100 = to_pixels(&slot, work(1920, 1080), None);
        assert_eq!(s100, PxRect { x: 0, y: 0, w: 960, h: 540 });
        // 125%：1920×1080 逻辑 → 2400×1350 物理
        let s125 = to_pixels(&slot, work(2400, 1350), None);
        assert_eq!(s125, PxRect { x: 0, y: 0, w: 1200, h: 675 });
        // 150%：→ 2880×1620 物理
        let s150 = to_pixels(&slot, work(2880, 1620), None);
        assert_eq!(s150, PxRect { x: 0, y: 0, w: 1440, h: 810 });

        // 三者占工作区的比例都应是 1/4
        for (r, w, h) in [(s100, 1920, 1080), (s125, 2400, 1350), (s150, 2880, 1620)] {
            let ratio = (r.w as f64 * r.h as f64) / (w as f64 * h as f64);
            assert!((ratio - 0.25).abs() < 1e-9, "比例应恒为 1/4，实际 {ratio}");
        }
    }

    /// 侧栏 + 副屏 + 缩放叠加（验收项 10 要求"含多屏 + 侧栏 + DPI"）。
    #[test]
    fn sidebar_and_second_monitor_combined() {
        let second = WorkArea { x: 2560, y: 0, w: 1920, h: 1080 };
        let sb = AiSidebar { enabled: true, edge: "right".into(), width: 0.25 };
        let half = Rect { x: 0.0, y: 0.0, w: 0.5, h: 1.0 };
        let px = to_pixels(&half, second, Some(&sb));
        // 可用宽 = 1920 * 0.75 = 1440；左半 = 720
        assert_eq!(px, PxRect { x: 2560, y: 0, w: 720, h: 1080 });
        assert!(px.x + px.w <= 2560 + 1440, "不得越过侧栏");
    }

    /// 布局文件写错（比例 > 1）时不应产生负数宽度。
    #[test]
    fn clamps_absurd_sidebar_ratio() {
        let work = work(1000, 500);
        let sb = AiSidebar { enabled: true, edge: "right".into(), width: 3.0 };
        let (_, usable_w) = usable_box(work, Some(&sb));
        assert_eq!(usable_w, 0, "比例应被夹到 1，可用宽度为 0 而不是负数");
        let px = to_pixels(&Rect { x: 0.0, y: 0.0, w: 1.0, h: 1.0 }, work, Some(&sb));
        assert!(px.w >= 0);
    }

    /// 侧栏未启用 / 未配置时，可用区域就是整个工作区。
    #[test]
    fn no_sidebar_uses_full_work_area() {
        let work = work(800, 600);
        assert_eq!(usable_box(work, None), (0, 800));
        let off = AiSidebar { enabled: false, edge: "right".into(), width: 0.5 };
        assert_eq!(usable_box(work, Some(&off)), (0, 800), "未启用不得扣宽");
    }
}
