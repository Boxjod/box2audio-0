# BoxAudio-0: 一二布布语音包合成工具

基于 [F5-TTS](https://github.com/SWivid/F5-TTS) 的 AI 语音合成工具，支持「一二」和「布布」两个动漫角色的语音生成，并支持上传参考音频自定义角色音色。

输入文字 → 选择角色 → 一键生成 AI 语音。

**在线体验（无需安装）**：[https://audio.box2ai.com](https://audio.box2ai.com/#/)

## 支持我们

如果这个项目对你有帮助，请给我们点一个 Star ⭐，这是对我们最大的鼓励！

[![Star this repo](https://img.shields.io/github/stars/Boxjod/box2audio-0?style=social)](https://github.com/Boxjod/box2audio-0)

## 系统要求

- **Python**: 3.10+（推荐 3.12）
- **ffmpeg**: 用于音频后处理（静音裁剪）
- **GPU**: 推荐 NVIDIA GPU + CUDA（CPU 也能运行，但速度较慢）
- **磁盘空间**: 需下载 F5-TTS 模型（~1.3GB）+ Vocos 声码器（~52MB）

### 安装 ffmpeg

```bash
# Ubuntu / Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

## 安装步骤

### 1. 创建虚拟环境

```bash
cd box2audio_open
python3 -m venv venv
source venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

**中国大陆用户**：如果下载缓慢，使用镜像加速：

```bash
# pip 镜像
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# HuggingFace 镜像（首次运行前设置，用于下载 F5-TTS 模型）
export HF_ENDPOINT=https://hf-mirror.com
```

### 3. 下载 F5-TTS 模型（必需）

F5-TTS v1 Base 是语音合成的核心模型（~1.3GB），另外还需要 Vocos 声码器（~52MB）。
模型会下载到系统默认缓存目录（`~/.cache/huggingface/hub/`），所有方式下载的模型均可被程序自动识别。

#### 方式一：从魔搭社区下载（推荐国内用户）

```bash
pip install modelscope

# 下载 F5-TTS v1 模型（~1.3GB）
modelscope download AI-ModelScope/F5-TTS F5TTS_v1_Base/model_1250000.safetensors
```

或使用 Git 克隆完整仓库（包含所有版本的权重）：

```bash
git lfs install
git clone https://www.modelscope.cn/AI-ModelScope/F5-TTS.git ~/.cache/modelscope/hub/AI-ModelScope/F5-TTS
```

> Vocos 声码器（`charactr/vocos-mel-24khz`）魔搭社区暂无镜像，首次启动时会自动从 HuggingFace 下载（~52MB），或通过方式二提前下载。

#### 方式二：从 HuggingFace 下载

```bash
# 中国大陆用户先设置镜像
export HF_ENDPOINT=https://hf-mirror.com

# 下载 F5-TTS v1 模型
huggingface-cli download SWivid/F5-TTS F5TTS_v1_Base/model_1250000.safetensors

# 下载 Vocos 声码器
huggingface-cli download charactr/vocos-mel-24khz
```

### 4. 下载 Whisper 模型（可选，用于自定义音色）

Whisper large-v3-turbo（~1.5GB）是 OpenAI 的语音识别模型，可用于自动识别参考音频中的文字。
当前自定义音色功能支持手动输入参考文字，**如不需要自动识别可跳过此步**。

#### 方式一：从魔搭社区下载（推荐国内用户）

```bash
pip install modelscope

# 下载 Whisper large-v3-turbo（~1.5GB）
modelscope download AI-ModelScope/whisper-large-v3-turbo
```

或使用 Git 克隆：

```bash
git lfs install
git clone https://www.modelscope.cn/AI-ModelScope/whisper-large-v3-turbo.git ~/.cache/modelscope/hub/AI-ModelScope/whisper-large-v3-turbo
```

#### 方式二：从 HuggingFace 下载

```bash
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download openai/whisper-large-v3-turbo
```

## 启动

```bash
source venv/bin/activate
export HF_ENDPOINT=https://hf-mirror.com  # 中国大陆用户需要设置
python app.py
```

启动后会在终端显示访问地址，默认为：http://localhost:7860

如果未提前下载模型，首次启动时会自动从 HuggingFace 下载 F5-TTS 模型和 Vocos 声码器，请确保网络畅通。

## 使用说明

1. 在浏览器中打开 http://localhost:7860
2. 在「输入文字」框中输入要合成的文字（最多 500 字）
3. 选择角色：布布 (bubu)、一二 (yier) 或 自定义 (custom)
4. 若选择「自定义」：上传一段 5-15 秒的参考音频，并输入音频中说的话
5. 调整语速（0.3~2.0，默认 1.0）
6. 点击「生成语音」按钮
7. 等待合成完成后，可在线播放或下载音频文件

## 项目结构

```
box2audio_open/
├── app.py                  # 主入口：TTS 引擎 + Gradio Web UI
├── requirements.txt        # Python 依赖
├── README.md               # 本文件
├── assets/
│   └── audio/
│       ├── bubu_self_introduction.wav   # 布布参考音频
│       └── yier_self_introduction.wav   # 一二参考音频
└── outputs/                # TTS 输出音频（自动创建）
```

## 常见问题

### Q: 首次启动非常慢？

A: 如果未提前下载模型，首次启动需要下载 F5-TTS（~1.3GB）和 Vocos（~52MB）。建议按照上方「下载 F5-TTS 模型」步骤提前下载。中国大陆用户推荐从魔搭社区下载，或设置 HuggingFace 镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

### Q: 提示 ffmpeg 相关错误？

A: 请确保已安装 ffmpeg：`sudo apt install ffmpeg`（Ubuntu）或 `brew install ffmpeg`（macOS）。ffmpeg 用于合成后的静音裁剪，如果没有安装，合成仍然可以工作，但音频首尾可能有多余的静音。

### Q: 提示 torchcodec 相关错误？

A: 新版 torchaudio（2.10+）默认使用 torchcodec 加载音频，torchcodec 需要系统安装的 ffmpeg 共享库。本项目已内置 soundfile 回退机制，正常情况下不会出现此错误。如果遇到，请确保 `soundfile` 已安装：

```bash
pip install soundfile
```

### Q: CUDA out of memory？

A: F5-TTS 模型需要约 2-4GB 显存。如果显存不足，模型会自动回退到 CPU 运行（速度较慢）。

### Q: 依赖安装很慢、下载 torch 很大？

A: PyTorch + CUDA 包体积较大（约 2-3GB）。建议使用国内 pip 镜像：

```bash
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

## 致谢

- [F5-TTS](https://github.com/SWivid/F5-TTS) — 底层语音合成模型
- [黄小B](https://www.douyin.com/user/MS4wLjABAAAAFtb6LcbnyYHL_C5i_hOHoC0W9jrKOk1z1dbCfVGS8aqtd_iDneHqtCIqfF6P-AQ0) — 角色 IP 来源
