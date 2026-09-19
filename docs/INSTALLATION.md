# 安装说明

AI 短剧整理器以 Docker 方式运行，适用于飞牛 fnOS、群晖、威联通及普通 Linux NAS。

## 运行要求

- x86_64 或 arm64 NAS
- Docker 24 或更新版本
- Docker Compose v2
- 来源目录可读
- 整理目录可写
- 浏览器能够访问 NAS 的 `8997` 端口

## 目录规划

容器只允许访问两个媒体根目录：

| 用途 | NAS 路径示例 | 容器路径 |
| --- | --- | --- |
| 刮削来源 | `/path/to/your/short-dramas` | `/source` |
| 整理输出 | `/path/to/your/media` | `/library` |
| 本地磁盘 | `/path/to/your/local-disk` | `/disks/local` |
| CD2 挂载 | `/path/to/your/cd2-mount` | `/disks/cd2` |
| 持久配置 | 项目目录下的 `config` | `/config` |

网页中的刮削目录和整理目录应填写容器路径，例如 `/source` 和 `/library/AI短剧`，不能填写 NAS 主机路径。

## Docker Compose 安装

1. 下载或克隆项目并进入目录。
2. 复制 `.env.example` 为 `.env`，填写 NAS 上实际的刮削目录和整理目录。
3. 启动服务：

   ```bash
   docker compose up -d --build
   ```

4. 浏览器访问：

   ```text
   http://NAS-IP:8997
   ```

5. 打开“设置”，保存默认的刮削目录、整理目录和整理模式；这些值会自动带入新任务，但每次任务均可修改。

设置页的“选择目录”按钮只显示已经映射进容器的目录。若要读取新的本地磁盘或 CD2/CloudDrive2 目录，请先在 `.env` 中修改 `LOCAL_DISK_ROOT` 或 `CD2_MOUNT_DIR`，再重新创建容器。

## 飞牛 fnOS 示例

例如可以在 `.env` 中填写：

```dotenv
SCRAPE_DIR=/vol1/你的用户目录/CloudNAS/CloudDrive/网盘名称/影视/短剧
ORGANIZE_DIR=/vol1/你的用户目录/media
LOCAL_DISK_ROOT=/vol1/你的用户目录
CD2_MOUNT_DIR=/vol1/你的用户目录/CloudNAS/CloudDrive2
```

## 首次使用

1. 进入“整理任务”，选择本次任务的短剧来源目录和整理目标目录。
2. 选择整理模式。点击“仅扫描此目录”可逐部预览；点击“扫描并整理此目录”可确认后批量处理全部扫描结果。程序不会在进入页面时预扫描媒体库。
3. 使用逐部模式时，在扫描结果中选择短剧，点击“预览整理”，检查目标目录、文件数量、总体积和冲突提示。
4. 勾选确认框后执行整理与刮削任务。
5. 在 Emby 中把整理目标添加为“电视节目”媒体库，然后扫描 Emby 媒体库。

## 整理模式

- **复制**：最安全，保留来源视频，但会占用额外存储空间。
- **硬链接**：不重复占用空间，但来源与整理目录必须在同一文件系统；CloudDrive 与本地磁盘通常不能硬链接。
- **原地整理**：不复制视频，只在来源文件夹生成封面和 NFO；目标目录设置不生效。

项目不提供移动或自动删除模式，避免误删云盘内容。
