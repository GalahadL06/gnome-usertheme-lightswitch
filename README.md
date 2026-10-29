# gnome-usertheme-lightswitch

按地理位置计算日出日落，并据此维护 GNOME 桌面的浅色/深色主题、图标包与动态壁纸。适用于被主题安装脚本接管了 libadwaita 样式、从而失去系统自动切换能力的桌面环境。

全部逻辑使用 Python 3 标准库实现，无第三方依赖，以普通用户权限运行，不需要 root。

## 功能

- 本地计算日出、日落、民用晨昏蒙影与太阳正午，不依赖网络或第三方天文接口。
- 一次切换同时维护 gsettings、GNOME Shell 面板主题与 libadwaita 用户样式三层状态。
- 读取 WinDynamicDesktop 的 `.ddw` 主题，按太阳高度角在四类图片之间轮换桌面壁纸。
- 由 systemd 用户定时器驱动，操作幂等，可自愈被其他工具改写的状态。
- 支持手动切换、暂停自动切换、强制重应用与自检。

## 工作原理

### 受控状态

GNOME 的浅色/深色并非单一开关，而是若干相互独立的状态。任一状态未更新，都会出现界面配色不一致。

| 层 | 位置 | 作用 |
|---|---|---|
| gsettings | `org.gnome.desktop.interface` 的 `gtk-theme`、`icon-theme`、`color-scheme` | GTK3 应用、图标主题、portal 与多数应用读取的偏好 |
| GNOME Shell | `org.gnome.shell.extensions.user-theme name` | 顶栏与概览的面板主题，需启用 User Themes 扩展 |
| libadwaita 覆盖 | `~/.config/gtk-4.0/gtk.css` 与 `gtk-dark.css` 两个符号链接 | GTK4 与 libadwaita 应用实际加载的用户样式 |
| 桌面壁纸 | `org.gnome.desktop.background` 的 `picture-uri`、`picture-uri-dark`、`picture-options` | 桌面背景 |

切换到浅色时，两个符号链接同时指向浅色样式，`gtk-application-prefer-dark-theme` 写为 `0`；切换到深色时取反。两个链接保持一致，使"应用偏好深色"和"应用偏好浅色"两条加载路径得到同一套配色。

### 切换判定

日出日落由 NOAA 太阳位置近似算法在本地计算，与公开参考数据相比误差在分钟级。判定区间为 `[日出 + 缓冲, 日落 − 缓冲)`：区间内为浅色，区间外为深色。`buffer_minutes` 默认为 0，即日出转入浅色、日落转入深色；设为 20 则推迟 20 分钟转浅、提前 20 分钟转深。

高纬度地区按当地当日是否发生日出日落判定极昼或极夜，此时固定使用浅色或深色。站点与机器时区相差较大时，事件时刻以该地太阳正午为锚点在前后一天的候选中择近，避免跨时区排布导致日出晚于日落。

### 调度模型

`lightswitch.timer` 每 5 分钟触发一次 `lightswitch tick`。tick 计算当前应有状态，与上一次应用结果及 `gsettings` 实际值比对，一致则不写入。

该模型相对"在日出与日落时刻各设一个定时器"的取舍：固定时刻的定时器在系统休眠、时区变更、夏令时切换或异地使用时全部失准，需要额外补偿逻辑；轮询模型在每次唤醒后自行收敛，代价是状态更新最多滞后 5 分钟。

## 系统要求

| 项目 | 要求 |
|---|---|
| 桌面环境 | GNOME 42 或更高，需 User Themes 扩展以切换面板主题 |
| 会话 | systemd 用户实例可用（`systemctl --user`） |
| 解释器 | Python 3.10 或更高，仅使用标准库 |
| 可选组件 | `nmcli`：按周边 AP 指纹定位；`python3-gi`：使用 GeoClue 定位 |
| 已验证环境 | GNOME 50、Python 3.14 |

## 安装

1. 获取仓库并进入目录：

   ```sh
   git clone <repository-url> ~/usertheme-lightswitch
   cd ~/usertheme-lightswitch
   ```

2. 安装命令入口与 systemd 用户单元：

   ```sh
   ./bin/lightswitch install
   ```

   该步骤写入 `~/.local/bin/lightswitch`、`~/.config/systemd/user/lightswitch.service` 与 `lightswitch.timer`，不修改系统目录。

3. 生成主题配置。工具会扫描 `~/.themes` 中成对的 `-Light` / `-Dark` 目录，并在图标目录中匹配同名图标包：

   ```sh
   ./bin/lightswitch detect --apply
   ```

   无成套主题时手工指定，字段值必须是实际存在的目录名：

   ```sh
   lightswitch config set \
     --light-theme Adwaita --light-icons Adwaita \
     --dark-theme Adwaita-dark --dark-icons Adwaita
   ```

   需要同步切换面板主题时，追加 `--light-shell` 与 `--dark-shell`；面板主题不参与切换时执行 `lightswitch config set --shell off`。

4. 设置坐标并启用自动切换：

   ```sh
   lightswitch location --city 北京
   lightswitch auto on
   ```

5. 验证：

   ```sh
   lightswitch doctor
   lightswitch status
   ```

   `doctor` 逐项检查样式文件、主题目录、图标包、schema、壁纸来源与定时器。全部通过时退出码为 0。

## 命令参考

| 命令 | 说明 |
|---|---|
| `lightswitch light` / `dark` / `toggle` | 切换到指定变体，或按当前状态取反 |
| `lightswitch auto on` / `auto off` / `stop` | 启用或停止自动切换，对应 systemd 定时器的启停 |
| `lightswitch refresh` | 按当前变体重新应用，修复被其他工具改写的符号链接与 gsettings |
| `lightswitch tick [--at TIME] [--dry-run]` | 按当前时间判定并应用一次；`--at` 接受 `18:30` 或 ISO 8601 时刻 |
| `lightswitch status [--json]` | 输出当前主题、日出日落、壁纸、下次切换与定时器状态 |
| `lightswitch config show` | 输出完整配置 |
| `lightswitch config set [选项]` | 修改主题、图标、Shell 主题、样式文件名、缓冲分钟数与面板跟随开关 |
| `lightswitch detect [--apply]` | 扫描已安装的浅/深色主题对 |
| `lightswitch location --city NAME` | 按地名解析坐标 |
| `lightswitch location --set LAT,LON` | 手动指定坐标 |
| `lightswitch location --wifi` | 按周边 AP 指纹查询 BeaconDB |
| `lightswitch location --ip` / `--geoclue` | 按出口 IP 或系统定位服务获取坐标 |
| `lightswitch location --clear` | 清除已保存坐标 |
| `lightswitch wallpaper use PATH` / `off` / `apply` / `status` | 载入、停用、按时刻应用与查看动态壁纸 |
| `lightswitch doctor` | 环境自检 |
| `lightswitch install` / `uninstall` | 安装或移除命令入口与定时器 |

退出码：

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 自检未通过、定时器操作失败，或未发现可用的主题对 |
| 2 | 参数或环境错误：缺少坐标、文件不可读、定位失败、主题样式缺失 |
| 3 | 坐标未通过时区一致性校验，未写入配置 |

## 定位

坐标仅用于计算太阳位置，保存在本地配置文件；`tick` 与 `status` 不发起网络请求。

| 方式 | 发送内容 | 说明 |
|---|---|---|
| `--city NAME` | 地名字符串 | 通过 Open-Meteo 地名服务解析，与出口 IP 无关 |
| `--set LAT,LON` | 无 | 适合精确到园区的位置或离线环境 |
| `--wifi` | 周边 AP 的 BSSID 与信号强度，`considerIp` 为 false | 依赖 BeaconDB 的覆盖范围 |
| `--ip` / `--geoclue` | 出口 IP 或系统定位服务 | 兜底方案；经代理、VPN 或 TUN 时返回出口所在地 |

写入配置前执行一致性校验：将该坐标的太阳正午换算到机器时区，与 12:00 相差超过 4 小时即判定为可疑来源，拒绝保存并提示改用 `--city`。`tick` 遇到同样情况拒绝切换，`status` 输出警告。确有异地调度需求时，加 `--force` 跳过校验。

`--geoclue` 依赖 GNOME 的"位置服务"总开关；该服务以 AP 数据库为主要数据源，缺少记录时返回与物理位置无关的结果，且不保证弹出授权提示。在隐私敏感或代理环境下不建议使用。

## 动态壁纸

### 主题格式

`.ddw` 是 zip 归档，包含一份 `theme.json` 与一组图片。图片文件名由 `imageFilename` 中的 `*` 替换为序号得到，分组由四个数组声明：`sunriseImageList`、`dayImageList`、`sunsetImageList`、`nightImageList`。`dayImageList`、`nightImageList` 与 `imageFilename` 为必需字段。

### 时段划分

时段边界与 WinDynamicDesktop 的实现一致，按太阳高度角划分：

| 时段 | 高度角边界 | 图片组 |
|---|---|---|
| 日出 | 民用黎明 −6° 至金色时段结束 +6° | `sunriseImageList` |
| 白天 | +6° 至当日金色时段开始 +6° | `dayImageList` |
| 日落 | +6° 至民用黄昏 −6° | `sunsetImageList` |
| 夜间 | 民用黄昏至次日民用黎明 | `nightImageList` |

每组的图片在该时段内均匀铺开，当前时刻取最后一个已生效的条目。夜间段跨越午夜，因此凌晨仍显示前一日夜间的图片。极昼或极夜时缺失的时段自动跳过。

### 应用与缓存

图片解压到 `~/.cache/lightswitch/wallpapers/<内容哈希>/`，同一主题只解压一次。应用时将 `picture-uri` 与 `picture-uri-dark` 设为同一张图片，`picture-options` 设为 `zoom`，避免浅色与深色模式显示不同背景。目标图片与当前一致时不写入 gsettings。

```sh
lightswitch wallpaper use ~/Pictures/Theme.ddw
lightswitch wallpaper status
lightswitch wallpaper apply --at 06:20
lightswitch wallpaper off
```

壁纸与主题相互独立：主题按浅色/深色切换，壁纸按太阳高度切换，二者在同一轮 tick 内完成。

## 配置参考

配置文件位于 `~/.config/lightswitch/config.json`，缺失字段取默认值。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `latitude` | number 或 null | null | 纬度，取值范围 −90 至 90 |
| `longitude` | number 或 null | null | 经度，取值范围 −180 至 180 |
| `buffer_minutes` | integer | 0 | 浅色推迟与深色提前的分钟数 |
| `apply_shell` | boolean | true | 是否切换 GNOME Shell 面板主题 |
| `light` | object | Adwaita | 浅色变体：`gtk`、`icons`、`shell`、`gtk4_css` |
| `dark` | object | Adwaita-dark | 深色变体，字段同上 |
| `wallpaper_ddw` | string 或 null | null | `.ddw` 文件绝对路径 |
| `wallpaper_enabled` | boolean | false | 是否参与壁纸轮换 |

`shell` 为空字符串时不修改面板主题。`gtk4_css` 是 `~/.config/gtk-4.0/` 下的文件名，主题安装脚本必须已生成该文件。

运行时文件位置：

| 路径 | 内容 |
|---|---|
| `~/.local/bin/lightswitch` | 命令入口，指向仓库内的 `bin/lightswitch` |
| `~/.config/systemd/user/lightswitch.{service,timer}` | 定时器单元 |
| `~/.local/state/lightswitch/state.json` | 上次应用的变体与时间 |
| `~/.cache/lightswitch/wallpapers/` | 壁纸解压缓存，可安全删除 |

`lightswitch.timer` 使用 `OnCalendar=*:0/5`、`Persistent=true`、`AccuracySec=30s`；服务单元为 `Type=oneshot`，执行 `lightswitch tick`。

## 故障排查

| 症状 | 原因 | 处置 |
|---|---|---|
| `doctor` 报告样式文件缺失 | 主题安装脚本未生成 `gtk-Light.css` 或 `gtk-Dark.css` | 重新运行该主题的安装脚本；确认 `config` 中 `gtk4_css` 与实际文件名一致 |
| 主题安装脚本无输出且立即退出 | 部分脚本使用 `setterm` 控制光标，`TERM=dumb` 触发脚本内的 `trap ERR` | 执行前设置 `export TERM=xterm-256color` |
| 切换后被自动改回 | 主题自带的图形切换器同样改写 `~/.config/gtk-4.0/gtk.css` | 下一轮 `tick` 会自动纠正，或立即执行 `lightswitch refresh` |
| 已运行的应用未变色 | GTK 应用不热重载用户样式 | 重新打开应用；GNOME Shell 面板为即时生效 |
| 定时器未运行 | 用户级定时器仅在登录会话内运行 | 需要无人登录时仍生效，执行 `loginctl enable-linger $USER` |
| `tick` 报坐标与时区不符 | 定位结果来自出口 IP 或系统定位服务的回落 | 执行 `lightswitch location --city <城市>` 重新设置 |
| 壁纸不切换 | `wallpaper_enabled` 为 false，或坐标缺失 | 执行 `lightswitch wallpaper use <文件>`，并确认已设置坐标 |

## 已知限制

- 状态更新粒度为 5 分钟，切换时刻与太阳事件最多相差 5 分钟。
- 锁屏壁纸由 `org.gnome.desktop.screensaver picture-uri` 控制，本工具不修改。
- 壁纸按整屏缩放（`zoom`），不区分多显示器与不同分辨率。
- 极昼极夜期间主题固定，不随太阳高度变化。
- 仅支持 systemd 用户实例；无 systemd 的发行版需自行以 cron 调用 `lightswitch tick`。

## 卸载

```sh
lightswitch uninstall
rm -rf ~/.cache/lightswitch ~/.config/lightswitch ~/.local/state/lightswitch
```

卸载后主题与壁纸维持当前状态，不会回滚。

## 开发

目录结构：

```
bin/lightswitch            命令入口，将 src 加入模块搜索路径
src/lightswitch/
    solar.py               太阳事件计算与切换判定，纯函数
    themes.py              变体到动作列表的规划，以及动作执行
    wallpaper.py           .ddw 解析、时段排布与壁纸动作
    location.py            坐标来源与地名校验
    scheduler.py           systemd 用户单元的安装与启停
    config.py              配置与状态读写
    cli.py                 命令行接口
tests/                     unittest 测试，含 gsettings 挡板
```

模块边界按职责划分：`solar.py` 与 `themes.plan()` 为纯函数，不产生副作用；`themes.execute()` 是唯一的写入点；`cli.py` 仅负责参数解析与输出格式。新增状态层时，应扩展 `plan()` 的动作列表，而不是在命令处理函数中直接写入。

测试：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

测试覆盖太阳事件（含极昼极夜、南半球、夏令时切换日、跨时区排布）、动作规划与执行（含幂等性与既有 INI 键保留）、`.ddw` 解析与时段排布、坐标来源与校验、以及各子命令的端到端行为。测试使用临时 HOME 与伪造的 `gsettings` 可执行文件，不修改真实桌面。

## 许可

MIT 许可，见 [LICENSE](LICENSE)。
