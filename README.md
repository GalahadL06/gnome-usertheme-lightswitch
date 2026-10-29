# lightswitch

按当地日出日落，自动切换 GNOME 的浅色/深色主题、图标包与桌面壁纸。

它补的是 GNOME 桌面上的一个空缺：系统自带的「自动切换深浅色」只改 `color-scheme`，一旦你用主题安装脚本接管了 `~/.config/gtk-4.0`（macOS 风格主题普遍这么做），libadwaita 就被钉死在某一份 CSS 上，自动切换随之失效；而壁纸更是完全没有跟随太阳的机制。lightswitch 用一个每 5 分钟自检的用户级定时器，把这几处状态一起校正，并且直接读取 WinDynamicDesktop 的 `.ddw` 主题按太阳高度换壁纸。

纯 Python 3 标准库，无第三方依赖，不需要 root。

## 它到底改了什么

主题切换在 GNOME 里不是一个开关，而是几处彼此独立的状态，漏掉任何一处都会出现「设置里是浅色、应用还是黑的」：

| 层 | 位置 | 作用 |
|---|---|---|
| gsettings | `org.gnome.desktop.interface` 的 `gtk-theme`、`icon-theme`、`color-scheme` | GTK3 应用、图标、portal 与多数应用读取的偏好 |
| GNOME Shell | `org.gnome.shell.extensions.user-theme name` | 顶栏与概览的面板主题（需 User Themes 扩展，可关闭） |
| libadwaita 覆盖 | `~/.config/gtk-4.0/gtk.css`、`gtk-dark.css` 两个软链 | 决定 GTK4/libadwaita 应用真正加载的 CSS |
| 壁纸 | `org.gnome.desktop.background` 的 `picture-uri`、`picture-uri-dark`、`picture-options` | 桌面背景，按 `.ddw` 主题的时间段取图 |

切换浅色时，两个软链一起指向浅色 CSS，同时把 `gtk-application-prefer-dark-theme` 写 0；深色反之。两个软链保持一致，是为了让「偏好深色」和「偏好浅色」两条加载路径不会各显示一套配色。

## 环境要求

- GNOME 桌面，systemd 用户实例可用（Ubuntu 22.04 及以上、GNOME 42 及以上；本项目在 GNOME 50 + Python 3.14 上验证）
- Python 3.10 或更高，只用标准库
- 可选：`nmcli`（按周边 AP 指纹定位时用）、`python3-gi`（仅在用 GeoClue 时需要，不推荐）

## 安装

```sh
git clone <仓库地址> ~/usertheme-lightswitch
cd ~/usertheme-lightswitch
./bin/lightswitch install          # 建 ~/.local/bin/lightswitch 软链，写入 systemd 用户单元
./bin/lightswitch detect --apply   # 扫描 ~/.themes 里成套的 -Light/-Dark 主题并写入配置
./bin/lightswitch location --city 北京
./bin/lightswitch auto on
```

`install` 不碰系统目录，只写 `~/.local/bin`、`~/.config/systemd/user`，因此不需要 sudo。`detect` 找不到成套主题时，用 `config set` 手写名字即可：

```sh
lightswitch config set \
  --light-theme MacTahoe-Light --light-icons MacTahoe-light \
  --dark-theme MacTahoe-Dark --dark-icons MacTahoe-dark \
  --light-shell MacTahoe-Light --dark-shell MacTahoe-Dark
```

前三个字段必须是 `~/.themes` 下真实存在的目录名，图标则是 `~/.icons` 或 `~/.local/share/icons` 下的目录名；`lightswitch doctor` 会逐项指出缺失。

## 命令

| 命令 | 作用 |
|---|---|
| `lightswitch light` / `dark` / `toggle` | 立刻切到指定变体 |
| `lightswitch auto on` / `auto off`（=`stop`） | 启用或停止自动切换 |
| `lightswitch refresh` | 按当前变体重应用一遍，修正被其他工具改回的软链或 gsettings |
| `lightswitch status [--json]` | 主题、日出日落、壁纸、下次切换、定时器状态 |
| `lightswitch tick [--at 2026-10-29T18:30] [--dry-run]` | 按当前时间判定并切换一次（定时器调用的就是它） |
| `lightswitch config show` / `config set ...` | 查看或修改浅/深色各自的主题、图标、Shell 主题与 CSS 文件名 |
| `lightswitch detect [--apply]` | 扫描已安装的浅/深色主题对 |
| `lightswitch location --city 城市` / `--set 纬度,经度` / `--wifi` / `--ip` / `--clear` | 位置来源，见下节 |
| `lightswitch wallpaper use 路径.ddw` / `off` / `apply` / `status` | 动态壁纸，见后文 |
| `lightswitch doctor` | 自检 CSS、主题目录、图标包、schema、壁纸与定时器 |
| `lightswitch install` / `uninstall` | 安装或移除命令入口与定时器 |

## 定位

坐标只用来算太阳位置，存本地 `~/.config/lightswitch/config.json`，`tick` 与 `status` 完全离线。取坐标有四种方式，按可信度排：

| 方式 | 往外发什么 | 适用场景 |
|---|---|---|
| `--city 城市名` | 只有地名 | 最稳妥，穿任何代理都准 |
| `--set 纬度,经度` | 什么都不发 | 想要精确到园区/校区，或离线环境 |
| `--wifi` | 周边 AP 的 BSSID 与信号强度（`considerIp: false`） | 所在区域在 BeaconDB 有覆盖时可用 |
| `--ip` / `--geoclue` | 出口 IP 或系统定位 | 兜底；走代理、VPN 或 TUN 时拿到的是代理落地，通常会被下面的检查拦下 |

入库前会做一次自洽检查：把该坐标的太阳正午换算到机器时区，偏离 12:00 超过 4 小时就判为可疑，不保存并提示改用 `--city`；`tick` 遇到同样的坐标会拒绝切换，`status` 会打 ⚠。确实要按异地坐标调度（例如给远程机器配另一地的作息）才加 `--force`。

`--geoclue` 走系统定位服务，只有在 GNOME 的「设置 → 隐私 → 位置服务」打开时才返回结果；它的地理数据来自 AP 数据库，缺记录时会给出与物理位置无关的结果，且这条路径不保证弹出授权提示。在意隐私或使用代理时不建议启用。

## 壁纸：直接吃 WinDynamicDesktop 的 .ddw

`.ddw` 就是一个 zip：一份 `theme.json` 加一组图片。本项目照搬 WinDynamicDesktop 的排布规则，而不是另立一套：

| 时段 | 太阳高度边界 | 图片组 |
|---|---|---|
| 日出 | 民用黎明 −6° → 金色时段结束 +6° | `sunriseImageList` |
| 白天 | +6° → 当日金色时段开始 +6° | `dayImageList` |
| 日落 | +6° → 民用黄昏 −6° | `sunsetImageList` |
| 夜间 | −6° → 次日民用黎明 | `nightImageList` |

每组的图片在自己的时段内均匀铺开，当前时刻取最后一个已生效的条目；夜间段跨到次日黎明，所以凌晨仍在用昨夜那张。边界数值与 WinDynamicDesktop 的 `SunriseSunset.cs` 一致：日出日落 −0.833°，民用晨昏蒙影 −6°，金色时段 ±6°。高纬度极昼极夜时对应时段为空，会自动跳过着色。

图片按 `imageFilename` 里的 `*` 替换成序号定位（例如 `shot_*.jpg` → `shot_1.jpg`），解压到 `~/.cache/lightswitch/wallpapers/<ddw 内容哈希>/`，同一主题只解一次。套用时 `picture-uri` 与 `picture-uri-dark` 指向同一张、`picture-options=zoom`，因此浅色深色两种模式不会各显示一张。

```sh
lightswitch wallpaper use ~/Pictures/SomeTheme.ddw   # 载入并立刻套用
lightswitch wallpaper status                         # 主题、当前图、下次换图时刻
lightswitch wallpaper apply --at 06:20               # 指定时刻取图，便于验证
lightswitch wallpaper off                            # 停止轮换，当前壁纸不动
```

壁纸跟太阳走，深浅色跟日出日落走，两者独立但在同一轮 tick 里完成。锁屏壁纸是另一个键（`org.gnome.desktop.screensaver picture-uri`），目前不在范围内。

## 调度与幂等

`systemd --user` 定时器每 5 分钟跑一次 `lightswitch tick`。tick 自己算此刻该是浅色还是深色、该用哪张壁纸，状态已经正确就什么都不写：它既比对上次应用的结果，也读一次当前 `gtk-theme` 与 `picture-uri`，所以别的工具（主题安装脚本、图形切换器）改过的状态，下一轮会被纠正回来。

没有用「日出、日落各设一个精确闹钟」，因为笔记本休眠、时区变更、夏令时切换、临时换城市都会让固定闹钟失准，而幂等轮询每次醒来都能自愈；代价是换图最多滞后 5 分钟（WinDynamicDesktop 自己是秒级事件调度）。

日志：`journalctl --user -u lightswitch.service -n 20`。

## 配置文件

`~/.config/lightswitch/config.json`，缺省值即 Adwaita 一套，按需覆盖：

```json
{
  "latitude": 39.9042,
  "longitude": 116.4074,
  "buffer_minutes": 0,
  "apply_shell": true,
  "light": {"gtk": "Adwaita", "icons": "Adwaita", "shell": "", "gtk4_css": "gtk-Light.css"},
  "dark": {"gtk": "Adwaita-dark", "icons": "Adwaita", "shell": "", "gtk4_css": "gtk-Dark.css"},
  "wallpaper_ddw": "/home/user/Pictures/Theme.ddw",
  "wallpaper_enabled": true
}
```

`buffer_minutes` 是切换缓冲：设 20 表示日出后 20 分钟才转浅色、日落前 20 分钟就转深色，默认 0 即严格按日出日落。`shell` 留空则该层不动。运行状态另存于 `~/.local/state/lightswitch/state.json`。

## 常见问题

**主题安装脚本没有生成 CSS。** `~/.config/gtk-4.0/` 下必须同时存在配置里指定的两套 CSS。某些主题的安装脚本在非交互环境下会静默失败：它用 `setterm` 关光标，`TERM=dumb` 会让这一步触发脚本内的 `trap ERR` 而整体退出，结果是主题目录被清空却没装回来。重跑前先 `export TERM=xterm-256color`。

**有图形切换器在抢软链。** 一些主题自带 GUI 切换器，同样改写 `~/.config/gtk-4.0/gtk.css`。手动用它切过之后，下一轮 `tick` 或一次 `lightswitch refresh` 会把状态纠回来。

**切完但旧窗口没变。** 已运行的 GTK 应用不会热重载用户 CSS，新开窗口才彻底生效；GNOME Shell 的顶栏是即时的。

**定时器不跑。** 默认只在用户登录期间运行；需要无人登录也生效时执行 `loginctl enable-linger $USER`。

**换了城市。** 重跑一次 `lightswitch location --city 新城市`，定时器不用动。

## 卸载

```sh
lightswitch uninstall      # 移除定时器与 ~/.local/bin 软链
rm -rf ~/.cache/lightswitch ~/.config/lightswitch ~/.local/state/lightswitch
```

主题与壁纸保持卸载前的状态，不会被改回去。

## 开发

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

模块分工：`solar.py` 是纯计算的太阳事件（日出日落、民用晨昏蒙影、金色时段，含极昼极夜与跨时区锚定）；`themes.py` 把变体翻译成动作列表 `plan()`，再由 `execute()` 落地；`wallpaper.py` 解析 `.ddw` 并生成时段排布；`location.py` 是三种坐标来源；`scheduler.py` 管 systemd 单元；`cli.py` 只做参数与输出。测试用临时 HOME 加一个假的 `gsettings` 挡板验证行为，不会碰真实桌面。

## 许可

MIT，见 [LICENSE](LICENSE)。
