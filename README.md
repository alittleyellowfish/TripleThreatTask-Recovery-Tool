# 三面混沌任务恢复工具

《影之刃零》Steam 版的本地 Windows 存档修复工具。适用于「三面混沌」任务失败、雪天镜林的第二场玉琮战未进入第三阶段的存档。

## 下载 1.0

在[版本 1.0 发布页](https://github.com/alittleyellowfish/TripleThreatTask-Recovery-Tool/releases/tag/v1.0)下载 `三面混沌任务恢复工具-v1.0.exe`，打开即可使用。

## 使用

1. 退出游戏并备份原存档。
2. 打开程序，拖入 Steam 库目录下的 `PBZSaveGame.sav`。也可以点击拖放区选择文件。

   ```text
   steamapps\common\PBZ\ProjectPBZ\Saved\SaveGames\Steam\<SteamID>\PBZSaveGame.sav
   ```

3. 程序按存档槽的游戏内保存时间选择最新一槽。修复成功后，查看目标档位和生成位置，或用「另存到文件夹…」保存结果。
4. 替换游戏存档后，从「载入游戏」进入结果页所示档位。重打时用「炽刃」打完第二阶段。

修复将镜林的第二场玉琮战及任务进度恢复到战前，保留第一次击杀和意识尘埃余额。程序收回「刺骨混沌」，若该武器已铸魂则返还一个「最初的混沌容器」。输出先写到独立目录，同名文件覆盖需要明确确认。

程序使用 Windows 上的 Microsoft Edge WebView2 Runtime。游戏程序需来自本地安装，找不到时可手动选择 `platform\steam\PBZ.exe`。

## 构建

在 Windows x64 上安装 Python 3.11，进入项目目录，在 PowerShell 中运行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build.ps1 -Python .\.venv\Scripts\python.exe
```

构建脚本从 [`VERSION`](VERSION) 读取版本号，并写入 Windows 文件的版本信息。1.0 版生成在 `dist/三面混沌任务恢复工具-v1.0.exe`。

## 目录

| 路径 | 内容 |
| --- | --- |
| `src/` | Windows 应用、界面、修复逻辑和存档编解码资源 |
| [`docs/third-party-notices.md`](docs/third-party-notices.md) | 第三方组件及字体字样来源 |
| `build/`、`dist/` | 本地构建缓存和发布产物 |

## 许可

本项目公开源码，原创部分采用 [PolyForm 非商业许可 1.0.0](LICENSE)。可以在许可范围内为非商业目的使用、修改和再分发。**禁止商用。** 再分发时须附上许可证文本或其官方链接，并保留[版权声明](NOTICE)。

第三方组件适用各自的许可。详见[第三方组件与素材声明](docs/third-party-notices.md)。
