# AI 短剧整理器

面向 Emby 的 NAS 自托管短剧媒体工作台。界面参考 MDC NG 的任务式工作流，每次任务可分别选择短剧来源和整理目标；提交任务后才扫描所选目录，再复制或硬链接视频并生成 `poster.jpg`、`fanart.jpg`、`tvshow.nfo` 和分集 NFO。

## 功能

- MDC NG 风格的主界面、整理任务、刮削记录和设置页
- 独立配置刮削目录与整理目录
- 不预扫描媒体库；创建任务并选择目录后才按需扫描
- 每个整理任务都可单独选择来源目录、目标目录和整理模式
- 支持“扫描并整理此目录”，后台逐部批量处理并显示完成进度
- 支持自动整理刮削：后台监控来源目录，新增短剧即按当前设置自动整理，刮削记录可一键清除
- 批量扫描后仍保留每部短剧的独立预览与整理入口
- 设置页目录选择器，可浏览 NAS 本地磁盘及 CD2/CloudDrive2 挂载目录
- 自动解析中文集数、`EP01` 和 `S01E01` 文件名
- 支持识别 `.strm` 剧集文件；strm 指向的本地视频或 http(s) 地址可访问时自动生成封面，不可访问时仍生成 NFO，可手动放置 `poster.jpg`
- 整理前预览目标文件、总体积和冲突
- 复制、硬链接、原地整理三种模式
- 两种封面获取方式：视频抽帧生成竖版海报和横版背景，或按剧名在线刮削官方封面（支持“先在线后抽帧”自动回退）
- 生成 Emby/Kodi 兼容的剧集与分集 NFO
- 可选的 Emby 媒体库刷新

详细文档：

- [安装说明](docs/INSTALLATION.md)
- [部署、升级与维护](docs/DEPLOYMENT.md)

## 安全设计

- 不删除或移动来源视频。
- 复制模式保留原文件；硬链接模式不额外占用视频空间，但要求同一文件系统。
- 目录访问仅限 Docker Compose 明确挂载的 `/source`、`/library`、`/disks/local` 和 `/disks/cd2`，阻止路径越界。
- 已有封面默认保留，只有勾选“重新生成已有封面”才会覆盖。

## 在 NAS 上部署

1. 将整个项目目录上传到 NAS，例如 `/vol1/docker/ai-drama-manager`。
2. 编辑 `docker-compose.yml`。左侧路径应是 NAS 中真实存在的短剧总目录：

   ```yaml
   volumes:
     - "${SCRAPE_DIR:-/path/to/your/short-dramas}:/source"
     - "${ORGANIZE_DIR:-/path/to/your/media}:/library"
     - "${LOCAL_DISK_ROOT:-/path/to/your/local-disk}:/disks/local"
     - "${CD2_MOUNT_DIR:-/path/to/your/cd2-mount}:/disks/cd2"
     - "./config:/config"
   ```

3. 如果 Emby 也运行在 Docker 中，确保两个容器可以互相访问。填写：

   ```yaml
   EMBY_URL: "http://你的Emby地址:8096"
   EMBY_API_KEY: "从 Emby 控制台获取的 API Key"
   ```

4. 在项目目录运行：

   ```bash
   docker compose up -d --build
   ```

5. 浏览器访问 `http://NAS地址:8997`。

## Emby 设置

在 Emby 控制台创建一个“电视节目”媒体库，媒体文件夹选择 `/media/AI短剧`。整理器中的 `/library/AI短剧` 与 Emby 中的 `/media/AI短剧` 应映射到同一个 NAS 媒体目录。

建议启用：

- 优先使用本地元数据
- 优先使用本地图片
- NFO 元数据读取器

如果只想收录一部剧，也可以把媒体库根目录指向短剧总目录，Emby 会把下面的每个文件夹识别成一部节目。

## 当前版本边界

- 封面来自视频抽帧，不调用付费 AI 服务；纯 strm 媒体库需要容器能访问 strm 记录的路径或 URL 才能自动出封面。
- 剧情简介可以在网页中手动填写。
- 适用于“一部短剧一个文件夹”的结构，并将分集规范化为 `S01E01` 样式。
- CloudDrive/115 挂载必须允许读取视频；生成图片和 NFO 还需要写入权限。
- 当前版本面向可信局域网，不应直接暴露到公网。
