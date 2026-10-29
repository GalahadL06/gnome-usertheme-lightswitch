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
./bin/lightswitch location --geoclue   # 在桌面终端里跑，会弹系统定位授权
./bin/lightswitch auto on
```

`install` 不需要 sudo：改的都是用户级路径（`~/.config`、`~/.local`、systemd 用户管理器）。在桌面终端而不是 SSH 里跑 `location --geoclue`，因为定位授权由 GNOME 会话里的 GeoClue 代理应答。

GeoClue 只在 GNOME 的「设置 → 隐私 → 位置服务」打开时才给坐标，否则会报 `Geolocation disabled for UID`；不想开总开关就手填坐标。坐标也可以手填，或用出口 IP 粗猜（走代理或 VPN 时不准）：

```sh
lightswitch location --set 39.9042,116.4074
lightswitch location --ip
lightswitch location --clear      # 清除坐标
```

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
| `lightswitch doctor` | 自检 CSS、主题目录、图标包、schema 与定时器 |
| `lightswitch uninstall` | 移除定时器与命令入口，主题保持现状 |

配置文件 `~/.config/lightswitch/config.json`，运行状态 `~/.local/state/lightswitch/state.json`。缓冲分钟数默认 0：日出即切浅色、日落即切深色；设成 20 则是日出后 20 分钟切浅、日落前 20 分钟切深。

## 调度方式

用一个 `systemd --user` 定时器每 5 分钟跑一次 `lightswitch tick`，由 tick 自己判断此刻该是浅色还是深色，状态已经正确就什么也不做。没有用「日出、日落各设一个精确闹钟」，因为笔记本休眠、时区变更、夏令时切换和换城市都会让固定闹钟失准，而幂等的轮询每次醒来都能自愈；开销只是一次本地天文计算。

`tick` 除了比对上一次应用的结果，还会读一次当前 `gtk-theme`：如果被上游 `install.sh -l` 或其他主题工具改回深色，下一轮就会被纠正。

## 与 MacTahoe 主题的关系

本工具不生成主题，只切开关。前提是 `~/.config/gtk-4.0/` 下同时存在 `gtk-Light.css` 与 `gtk-Dark.css`——MacTahoe 的 `install.sh -l` 每次都会把两套 CSS 一起生成出来。

两个实操坑：

- `install.sh` 在非交互环境下会静默失败并退出 1：它用 `setterm` 关光标，而 `TERM=dumb` 会让这一步触发脚本里的 `trap ERR`，主题文件一个都没装成。跑之前设 `TERM=xterm-256color`。
- 新版上游会顺手装一个 `gnome-theme-switcher` 图形切换器，它同样改 `~/.config/gtk-4.0/gtk.css` 软链。手动用它切过之后，下一轮 `tick`（或一次 `lightswitch refresh`）会把状态纠回来，两者不会长期打架。

## 另一台 Linux 机器

```sh
git clone <本仓库> ~/usertheme-lightswitch    # 或 rsync 整个目录
cd ~/usertheme-lightswitch && ./bin/lightswitch install
./bin/lightswitch location --geoclue
./bin/lightswitch auto on
```

换机器只需重跑 `location`；主题名不同就用 `lightswitch config set` 改成那台机器上实际安装的浅/深色主题与图标包名（`doctor` 会指出哪一项不存在）。

## 开发

纯 Python 3 标准库，无第三方依赖，用 `unittest`：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

`src/lightswitch/solar.py` 的日出日落算法与 open-meteo 的公开数据逐分钟一致（北京 2026-10-29：06:39 / 17:16），并覆盖极昼、极夜、南半球与夏令时切换日。`themes.py` 的 `plan()` 是纯函数，测试用临时 HOME 加一个假的 `gsettings` 挡板验证行为，不会碰真实桌面。
