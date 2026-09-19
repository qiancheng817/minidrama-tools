# 部署、升级与维护

## 服务结构

- 容器名称：`ai-drama-manager`
- Web 端口：`8097`
- 容器应用端口：`8096`
- 配置目录：`./config`
- 配置文件：`./config/settings.json`
- 任务记录：`./config/jobs.json`

封面生成依赖容器内的 FFmpeg、Pillow 和 Noto CJK 字体，构建镜像时会自动安装。

## 启动和状态检查

```bash
docker compose up -d
docker compose ps
curl http://127.0.0.1:8097/health
```

健康接口返回 `ok: true` 即表示应用正常运行。

## 更换磁盘或 CD2 目录

网页只能选择 Docker 已授权的目录。编辑 `.env` 中的 `LOCAL_DISK_ROOT` 和 `CD2_MOUNT_DIR`，然后执行 `docker compose up -d --build`。重新进入设置页，即可从目录选择器浏览 `/disks/local` 和 `/disks/cd2`。无需把 NAS 整个系统根目录暴露给容器。

## 查看日志

```bash
docker compose logs --tail=100 ai-drama-manager
```

持续查看日志：

```bash
docker compose logs -f ai-drama-manager
```

## 升级

升级前备份配置：

```bash
cp -a config config.backup
```

更新代码后重新构建：

```bash
docker compose up -d --build
```

配置与任务记录位于挂载目录中，重新构建容器不会丢失。

## 停止和卸载

停止服务：

```bash
docker compose stop
```

移除应用容器和项目网络：

```bash
docker compose down
```

以上命令不会删除来源视频、整理结果或 `config` 配置目录。不要添加 `-v` 参数，避免误删其他持久卷。

## Emby 配置

整理器写入的 NAS 目录为：

```text
/path/to/your/media/AI短剧
```

如果 Emby 容器把同一个 NAS 媒体目录映射为 `/media`，则应在 Emby 中添加：

```text
/media/AI短剧
```

媒体库类型选择“电视节目”，并启用本地 NFO 和本地图片读取。

如果希望网页按钮直接刷新 Emby，请在设置页填写 Emby 地址和 API Key。API Key 保存在 NAS 本地 `config/settings.json`，不要提交到 GitHub。

## 权限排查

如果扫描不到视频：

1. 确认 CloudDrive 挂载在线。
2. 确认 `docker-compose.yml` 左侧 NAS 路径正确。
3. 在容器内检查 `/source` 是否可见。

如果无法写入封面或 NFO：

1. 确认整理目录存在并可写。
2. CloudDrive 原地整理需要云盘挂载支持写入。
3. 改用 `/library/AI短剧` 的复制模式可避免在云盘来源中写入。

## 网络安全

当前版本面向可信家庭局域网，未内置登录系统。不要直接把 `8097` 暴露到公网。需要远程访问时，建议使用 VPN，或在带身份认证的反向代理后面访问。
