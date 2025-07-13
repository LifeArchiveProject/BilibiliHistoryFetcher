<p align="center">
    <img src="./logo.png" width="500" />
</p>

<div align="center">
    <h1>BilibiliHistoryFetcher - 哔哩哔哩历史记录获取与分析工具</h1>
    <img src="https://img.shields.io/github/v/tag/2977094657/BilibiliHistoryFetcher" />
    <img src="https://img.shields.io/github/stars/2977094657/BilibiliHistoryFetcher" />
    <img src="https://img.shields.io/github/forks/2977094657/BilibiliHistoryFetcher" />
    <img src="https://img.shields.io/github/last-commit/2977094657/BilibiliHistoryFetcher" />
    <img src="https://img.shields.io/github/license/2977094657/BilibiliHistoryFetcher" />
    <img src="https://img.shields.io/badge/Python-3776AB?logo=Python&logoColor=white" />
    <img src="https://img.shields.io/badge/FastAPI-009688?logo=FastAPI&logoColor=white" />
    <img src="https://img.shields.io/badge/SQLite-003B57?logo=SQLite&logoColor=white" />
</div>

## 介绍
该项目用于获取、处理、分析和可视化哔哩哔哩用户的观看历史数据。它提供了完整的数据处理流程，从数据获取到可视化展示，并支持自动化运行和邮件通知。

## 配套前端
请前往此项目 [BiliHistoryFrontend](https://github.com/2977094657/BiliHistoryFrontend) 获取配套的前端界面

## 主要功能

- [x] 获取历史记录
- [x] 年度总结
- [x] 视频和图片下载
  - [x] 一键下载用户所有投稿视频
- [x] 自动化任务
- [x] AI 摘要
- [x] 获取用户评论
- [x] 获取收藏夹
  - [x] 批量收藏
  - [x] 修复失效视频
  - [x] 一键下载收藏夹所有视频
- [x] 获取视频被全站观看的总时长

## 后续开发计划

项目正在积极开发中，您可以在我们的 [GitHub 项目计划页面](https://github.com/users/2977094657/projects/2) 查看最新的开发路线图和即将实现的功能。

## 交流群

如果您在使用过程中有任何问题或想与其他用户交流使用心得，欢迎加入我们的QQ交流群[1030089634](https://qm.qq.com/q/k6MZXcofLy)：

<p align="center">
    <img src="./Qun.png" width="300" />
</p>

## 系统要求

- Python 3.10+
- SQLite 3
- FFmpeg（用于视频下载）
- 必要的 Python 包（见 requirements.txt）

## 快速开始

#### 使用 Docker 安装
由 [@eli-yip](https://github.com/eli-yip) 实现 ([#30](https://github.com/2977094657/BilibiliHistoryFetcher/pull/30))
1. 安装 [Docker](https://docs.docker.com/get-started/get-docker/)
2. 根据您的系统构建 Docker 镜像：
   ```bash
   # 使用 NVIDIA 显卡
   docker build -t bilibili-api:dev -f docker/Dockerfile.cuda .
   ```
   ```bash
   # 使用 CPU
   docker build -t bilibili-api:dev -f docker/Dockerfile.cpu .
   ```
3. 创建 Docker 容器：
   ```bash
   # 使用 NVIDIA 显卡
   docker run -d -v ./config:/app/config -v ./output:/app/output -p 8899:8899 --gpus all --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 --name bilibili-api bilibili-api:dev
   ```
   ```bash
   # 使用 CPU
   docker run -d -v ./config:/app/config -v ./output:/app/output -p 8899:8899 --name bilibili-api bilibili-api:dev
   ```

   挂载目录说明：
   - `./config:/app/config`：配置文件目录，用于存储 SESSDATA 和其他配置
   - `./output:/app/output`：输出目录，用于存储下载的视频、图片和生成的数据

#### 使用 Docker Compose 部署

本项目提供了Docker Compose配置，实现一键部署前后端服务，您只需要一个`docker-compose.yml`文件即可完成整个部署，无需手动构建镜像。

1. 确保已安装 [Docker](https://docs.docker.com/get-started/get-docker/) 和 [Docker Compose](https://docs.docker.com/compose/install/)

2. 下载`docker-compose.yml`文件：
   - 直接从[这里](https://raw.githubusercontent.com/2977094657/BilibiliHistoryFetcher/master/docker-compose.yml)下载
   - 或使用以下命令下载：
     ```bash
     curl -O https://raw.githubusercontent.com/2977094657/BilibiliHistoryFetcher/master/docker-compose.yml
     # 或
     wget https://raw.githubusercontent.com/2977094657/BilibiliHistoryFetcher/master/docker-compose.yml
     ```

3. 使用Docker Compose启动服务：
   ```bash
   docker-compose up -d
   ```

4. 服务启动后访问：
   - 前端界面：http://localhost:5173
   - 后端API：http://localhost:8899
   - API文档：http://localhost:8899/docs

#### [通过 1Panel 部署](https://github.com/2977094657/BilibiliHistoryFetcher/discussions/65)
由社区贡献者 [@QYG2297248353](https://github.com/QYG2297248353) 实现 ([#66](https://github.com/2977094657/BilibiliHistoryFetcher/pull/66))

#### 使用 uv 安装 
由社区贡献者 [@eli-yip](https://github.com/eli-yip) 实现 ([#30](https://github.com/2977094657/BilibiliHistoryFetcher/pull/30))

1. 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)
2. 在项目根目录运行：
   ```bash
   # 安装依赖
   uv sync
   ```

   ```bash
   # 运行程序
   uv run main.py
   ```

#### 使用传统 pip 方式安装

如果您更喜欢使用传统的 pip 作为包管理器，可以按照以下步骤操作：

1. **安装依赖**

```bash
pip install -r requirements.txt
```

2. **运行程序**
```bash
python main.py
```

## API 接口

基础 URL: `http://localhost:8899`

完整 API 文档访问：`http://localhost:8899/docs`

## 应用打包

本项目提供了自动化打包脚本，可以将应用打包成独立的可执行文件，便于分发和部署。打包过程会自动处理依赖并清理敏感信息。

**打包前准备**

确保已经安装了 PyInstaller：

```bash
pip install pyinstaller
```

**打包命令**

使用以下命令进行打包：

```bash
python build.py
```

**打包完成后**

- 输出目录：`dist/BilibiliHistoryAnalyzer/`

**敏感信息处理**

打包过程会自动处理配置文件中的敏感信息：

- 创建临时清理过的配置文件，替换以下敏感字段为示例值：
  - `SESSDATA`：替换为"你的 SESSDATA"
  - `email`：邮箱相关信息替换为示例邮箱地址和说明
  - `ssl_certfile`/`ssl_keyfile`：替换为示例路径
  - `api_key`：替换为"你的 API 密钥"

- 打包完成后，临时文件会被自动删除
- 打包版本中的配置文件包含原始结构但敏感字段被替换为示例值，用户需要首次运行时填写实际信息

**运行打包后的应用**

在目标系统上直接运行可执行文件：

```
# Windows系统
BilibiliHistoryAnalyzer.exe
```

## 贡献指南

1. Fork 项目
2. 创建特性分支
3. 提交更改
4. 发起 Pull Request

## 致谢

- [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect) - 哔哩哔哩-API 收集整理，本项目使用其 API 接口获取 B 站用户数据
- [Yutto](https://yutto.nyakku.moe/) - 可爱的 B 站视频下载工具，本项目使用其进行视频下载功能
- [FasterWhisper](https://github.com/SYSTRAN/faster-whisper) - 音频转文字，本项目使用其进行视频音频转文字功能
- [DeepSeek](https://github.com/deepseek-ai/DeepSeek-R1) - DeepSeek AI API，本项目使用其进行 AI 摘要生成
- [one-balance](https://github.com/glidea/one-balance) - 智能的 AI API 密钥负载均衡器，提供更稳定可靠的 AI 服务调用
- [ArtPlayer](https://github.com/zhw2590582/ArtPlayer) - 强大且灵活的 HTML5 视频播放器
- [aicu.cc](https://www.aicu.cc/) - 第三方 B 站用户评论 API
- [方舟像素字体](https://github.com/TakWolf/ark-pixel-font) - 开源的泛中日韩像素字体
- [缝合像素字体](https://github.com/TakWolf/fusion-pixel-font) - 混搭风格的像素字体
- [小黑盒用户 shengyI](https://www.xiaoheihe.cn/app/bbs/link/153880174) - 视频观看总时长功能思路提供者
- 所有贡献者，特别感谢:
  - [@eli-yip](https://github.com/eli-yip) 对 Docker 部署的贡献
  - [@QYG2297248353](https://github.com/QYG2297248353) 对 1Panel 部署的贡献

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=2977094657/BilibiliHistoryFetcher&type=Date)](https://star-history.com/#2977094657/BilibiliHistoryFetcher&Date)