# lightswitch

按当地日出日落自动切换 GNOME 的浅色/深色主题、图标包与 libadwaita 配色。为 MacTahoe 这类用 `install.sh -l` 接管了 `~/.config/gtk-4.0` 的主题而写：那种安装方式让 GNOME 自带的「自动切换深浅色」失效，本工具用系统定时器补回这一能力。

## 它改了什么

主题切换在 GNOME 里其实是三处状态，缺一处就会出现「设置里是浅色、应用还是黑的」：

| 层 | 位置 | 作用 |
|---|---|---|
| gsettings | `org.gnome.desktop.interface` 的 `gtk-theme`、`icon-theme`、`color-scheme` | GTK3 应用、图标、portal 与各类应用读取的偏好 |
| GNOME Shell | `org.gnome.shell.extensions.user-theme name` | 顶栏与概览的面板主题（需 User Themes 扩展） |
| libadwaita 覆盖 | `~/.config/gtk-4.0/gtk.css`、`gtk-dark.css` 软链 | 决定 GTK4/libadwaita 应用真正用的 CSS；MacTahoe 的 `-l` 把它固定成了深色 |

切换时把两个软链一起指向 `gtk-Light.css` 或 `gtk-Dark.css`，同时把 `gtk-application-prefer-dark-theme` 写成对应值，深色偏好与浅色偏好两条加载路径就不会互相打架。资源文件（`assets/`、`windows-assets/`）里同时含浅色与 `-dark` 两套图，所以改软链足够，不需要重跑 `install.sh`。

## 安装

```sh
cd "/home/galahadl/文件/usertheme-lightswitch"
./bin/lightswitch install        # 建 ~/.local/bin/lightswitch 软链，写入 systemd 用户单元
./bin/lightswitch location --city 哈尔滨   # 或 --set 纬度,经度；都不依赖出口 IP
./bin/lightswitch auto on
```

`install` 不需要 sudo：改的都是用户级路径（`~/.config`、`~/.local`、systemd 用户管理器）。

## 定位：代理环境下怎么取到真坐标

这台机器常年挂着 Clash Verge 的 TUN，任何按**出口 IP** 推位置的服务都会返回代理落地（实测拿到洛杉矶）。GeoClue 2.7 的可执行文件里只内嵌了一个端点 `https://api.beacondb.net/v1/geolocate`，也就是它和本工具的 `--wifi` 用的是同一个 AP 数据库；校园网这类 AP 在库里没有记录时它就查不到，转而给出一个与 AP 无关的结果，而且这条路径不保证弹授权——所以它不适合当默认来源。

四类取法，按可信度排：

| 方式 | 往外发什么 | 说明 |
|---|---|---|
| `lightswitch location --city 哈尔滨` | 只有地名 | 与出口 IP 无关，穿 TUN 也准；返回后仍会做时区自洽检查 |
| `lightswitch location --set 45.78,126.68` | 什么都不发 | 想要校区级精度时用，离线可用 |
| `lightswitch location --wifi` | 只发周边 AP 的 BSSID 与信号强度 | 不含 IP 信息，但 BeaconDB 对中国大陆覆盖很薄，校园 AP 实测 404 |
| `lightswitch location --ip` / `--geoclue` | IP 或系统定位 | 兜底，TUN 环境下大概率是落地位置，通常会被自洽检查拦下（`--force` 可越过） |

坐标只写在 `~/.config/lightswitch/config.json`，除上述查询外不发往任何地方；`tick` 与 `status` 完全离线。

## 命令

| 命令 | 作用 |
|---|---|
| `lightswitch light` / `dark` / `toggle` | 立刻切到指定变体 |
| `lightswitch auto on` / `auto off` / `stop` | 启用或停止自动切换（systemd 用户定时器） |
| `lightswitch refresh` | 按当前变体重应用一遍：修软链、补 gsettings、清掉被上游脚本改回的深色 |
| `lightswitch status [--json]` | 当前主题、日出日落、下次切换、定时器状态 |
| `lightswitch tick [--at 2026-10-29T18:30] [--dry-run]` | 按当前时间核对并切换一次；`--at` 用于验证判定 |
| `lightswitch config show` | 查看浅色/深色各自用的主题、图标、Shell 主题与 CSS |
| `lightswitch config set --light-theme ... --light-icons ... --dark-theme ... --dark-icons ... --buffer 20 --shell off` | 改配置 |
| `lightswitch wallpaper use/off/apply/status` | 按 .ddw 随时段轮换壁纸，见下一节 |
| `lightswitch doctor` | 自检 CSS、主题目录、图标包、schema、壁纸与定时器 |
| `lightswitch uninstall` | 移除定时器与命令入口，主题保持现状 |

配置文件 `~/.config/lightswitch/config.json`，运行状态 `~/.local/state/lightswitch/state.json`。缓冲分钟数默认 0：日出即切浅色、日落即切深色；设成 20 则是日出后 20 分钟切浅、日落前 20 分钟切深。

## 调度方式

用一个 `systemd --user` 定时器每 5 分钟跑一次 `lightswitch tick`，由 tick 自己判断此刻该是浅色还是深色，状态已经正确就什么也不做。没有用「日出、日落各设一个精确闹钟」，因为笔记本休眠、时区变更、夏令时切换和换城市都会让固定闹钟失准，而幂等的轮询每次醒来都能自愈；开销只是一次本地天文计算。

`tick` 除了比对上一次应用的结果，还会读一次当前 `gtk-theme`：如果被上游 `install.sh -l` 或其他主题工具改回深色，下一轮就会被纠正。

## 壁纸：直接吃 WinDynamicDesktop 的 .ddw

`.ddw` 就是一个 zip：一份 `theme.json` 加一组图片。工具照搬了 WinDynamicDesktop 的排布方式，而不是自己发明一套：

| 时段 | 太阳高度边界 | 用哪组图 |
|---|---|---|
| 日出 | 民用黎明 −6° → 金色时段结束 +6° | `sunriseImageList` |
| 白天 | +6° → 当日金色时段开始 +6° | `dayImageList` |
| 日落 | +6° → 民用黄昏 −6° | `sunsetImageList` |
| 夜间 | −6° → 次日民用黎明 | `nightImageList` |

每组图片在自己那段时间里**均匀铺开**（WinDynamicDesktop 的 `SolarScheduler.GetAllImageTimes` 就是这么算的），当前时刻取最后一个已生效的条目；夜间段跨到次日黎明，所以凌晨仍在用昨夜那张。边界按 `SunriseSunset.cs` 的口径：日出日落 −0.833°、民用晨昏蒙影 −6°、金色时段 ±6°。高纬度极昼极夜时对应段为空，会自然跳过着色。

图片按 `imageFilename` 里的 `*` 替换成序号定位（如 `amalfi_6K_fp_*.jpg`），解压到 `~/.cache/lightswitch/wallpapers/<ddw 内容哈希>/`，同一个主题只解一次。套用是 `org.gnome.desktop.background` 的 `picture-uri` 与 `picture-uri-dark` 同时指向同一张，`picture-options=zoom`，因此浅色深色两种模式不会各显示一张。当前图与目标一致时 `tick` 不写 gsettings，日志里只会看到「已生效」。

```sh
lightswitch wallpaper use ~/下載/Sony_Alpha_Clock_Amalfi_6K.ddw   # 载入并立刻套用
lightswitch wallpaper status        # 主题、当前图、下次换图时刻
lightswitch wallpaper apply --at 06:20   # 指定时刻取图，便于验证
lightswitch wallpaper off           # 停止轮换，当前壁纸不动
```

壁纸跟着太阳走，深浅色主题跟着日出日落走，两者互相独立：黄昏后主题已转深色，壁纸也会在民用黄昏那一刻换成夜景。定时器仍是 5 分钟一格，所以换图最多滞后 5 分钟（WinDynamicDesktop 自己是按秒级事件调度，这里刻意用轮询换取休眠与换城市后的自愈）。109 MB 的 6K 主题解出来也是 109 MB，缓存可以直接删，下次载入会重建。

## 与 MacTahoe 主题的关系

本工具不生成主题，只切开关。前提是 `~/.config/gtk-4.0/` 下同时存在 `gtk-Light.css` 与 `gtk-Dark.css`——MacTahoe 的 `install.sh -l` 每次都会把两套 CSS 一起生成出来。

两个实操坑：

- `install.sh` 在非交互环境下会静默失败并退出 1：它用 `setterm` 关光标，而 `TERM=dumb` 会让这一步触发脚本里的 `trap ERR`，主题文件一个都没装成。跑之前设 `TERM=xterm-256color`。
- 新版上游会顺手装一个 `gnome-theme-switcher` 图形切换器，它同样改 `~/.config/gtk-4.0/gtk.css` 软链。手动用它切过之后，下一轮 `tick`（或一次 `lightswitch refresh`）会把状态纠回来，两者不会长期打架。

## 另一台 Linux 机器

```sh
git clone <本仓库> ~/usertheme-lightswitch    # 或 rsync 整个目录
cd ~/usertheme-lightswitch && ./bin/lightswitch install
./bin/lightswitch location --city <城市>
./bin/lightswitch auto on
```

换机器只需重跑 `location --city`；主题名不同就用 `lightswitch config set` 改成那台机器上实际安装的浅/深色主题与图标包名（`doctor` 会指出哪一项不存在）。

## 开发

纯 Python 3 标准库，无第三方依赖，用 `unittest`：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

`src/lightswitch/solar.py` 的日出日落算法与 open-meteo 的公开数据逐分钟一致（北京 2026-10-29：06:39 / 17:16），并覆盖极昼、极夜、南半球与夏令时切换日。`themes.py` 的 `plan()` 是纯函数，测试用临时 HOME 加一个假的 `gsettings` 挡板验证行为，不会碰真实桌面。
