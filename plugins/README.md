# plugins/ —— 第三方插件目录

每个插件一个独立子目录：

```
plugins/
├── examples/                  ← 阶段9 交付的两个示例（复制到插件根后安装）
│   ├── com.example.pomodoro/  ← 番茄钟：data:own + ui:widget
│   └── com.example.music/     ← 正在播放：system:media + ui:widget
└── com.example.<name>/        ← 已安装的插件在 <data_dir>/plugins/ 下
```

## 开发指南

见 `docs/plugin-dev-guide.md`（manifest 格式、桥协议、权限清单、调试方法）。

## 验证插件架构成功的标准（声明性 · 非可测试）

> 写一个新插件，零核心代码改动即能跑起来。

阶段9 已落地验证：examples/ 两个插件**零核心代码改动**安装即用。