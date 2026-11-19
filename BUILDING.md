# 构建与本地检查

版本唯一值见 [VERSION](VERSION)，当前为 `v0.2.0-rc.1`。本地构建只生成白名单源码与安装材料，不自行执行Git操作、上传GitHub或部署TeachClaw。发布目标为 [awei0728/kcsz-course-survey](https://github.com/awei0728/kcsz-course-survey)，历史 `v0.1.0-rc.1` 已发布并保留，不覆盖其标签或附件。

本版软件预发布包含18目标候选组卷、指定总题数与双格式导出。所有候选仍未获正式施测许可；`public_release_ready`只描述用户已授权的软件包装准备状态，不认证量表或目标平台导入。

## 运行和验证

使用已有Python3.10+；生产核心只使用标准库，开发和构建不调用模型或外部服务。当前主开发检查使用3.14.7，旧来源版另有3.12.14验证记录，最低3.10尚未单独实测。

从实际Skill根目录运行，或用脚本绝对路径：

```powershell
python -B scripts/survey_data.py validate
python -B scripts/candidate_data.py validate
python -B -m unittest discover -s tests -v
python -B scripts/build_release.py
```

完整平台发布还须从monorepo根运行AGENTS.md规定的Gateway、Python客户端、仓库政策和离线检查。开发依赖在仓库根 `requirements-dev.txt` 管理，不加入生产survey环境。检查结果应如实记录，未完成项不能改称已通过。

## 构建结果

默认创建独立 `release-candidate/<版本>-<运行标识>/`：

```text
source/kcsz-course-survey/
kcsz-course-survey-v0.2.0-rc.1-workbuddy.zip
manifest.json
SHA256SUMS
release-notes.md
```

返回UTF-8 JSON，含上述实际路径；0表示本地完成，1表示构建失败。可用 `--output-dir` 选择其他可写父目录。显式 `--candidate-id` 已存在时拒绝覆盖；失败目录保留 `BUILD-INCOMPLETE`，不可当作完成产物。来源数据、模板、脚本等目录不得作为构建输出位置。

## 白名单与校验

包内`.gitattributes`禁止Git自动转换换行，以保持导入数据、维度证据和发布清单中逐文件SHA256的字节一致性；源码检出与安装包使用同一输入字节。

[build_release.py](scripts/build_release.py) 的 `PUBLIC_FILES` 明确列出全部打包文件。源码快照与ZIP使用相同名单，包括新旧Python入口、必要说明、旧16来源JSON与2份PDF、新候选数据、维度说明原文、学习通模板及配置、测试、许可证和版本文件。

构建检查：

- 旧目录仍为12项目、16来源版本，PDF哈希与目录一致。
- 新候选为18项目、482题、505来源、188核心、294备份，原始30字段及引用完整。
- 三个主维度已确认，来源Markdown和学习通模板哈希正确。
- 所有本地Markdown引用均位于发布白名单中。
- ZIP成员、根目录及字节与源码快照一致。

不复制父仓库或开发机配置。`.git`、虚拟环境、缓存、历史output、tmp、发布工作区、运行日志、私密配置和开发审计资料不进入公开源码。安装ZIP、发布清单及校验文件作为Release附件，不提交进发布源码历史。

ZIP按相对路径排序，时间固定1980-01-01，权限及压缩等级固定。相同输入字节和Python/zlib环境下重复构建应得到相同ZIP、manifest、SHA256SUMS与发布说明；跨压缩库版本不保证ZIP字节相同，可独立比较文件哈希。

## 独立安装与发布验证

将ZIP独立解压到新目录，从其他cwd执行两套validate，再生成单目标默认、单目标指定题数、多目标默认和多目标指定题数的TXT/XLS；核对数量、选题、来源映射和主文件哈希。不要通过原开发路径读取资源来伪装移位运行成功。

GitHub发布应核实已有main及旧标签，在独立发布快照中追加本版提交，不推送父monorepo历史、不强推或移动旧标签。上传本次生成的四份附件后重新下载，核对大小与SHA-256。构建器本身始终报告 `remote_release_status=not_published_by_builder`，远端发布状态由发布过程单独验证。

TeachClaw宿主插件在monorepo维护。Skill ZIP不修改QQ账号、服务配置或插件，运行接入见 [TeachClaw说明](references/teach-claw.md)。本地协议测试、真实跨环境执行及QQ实际收件是不同证据，部署记录分别报告。

原创代码采用 [MIT](LICENSE)。候选交接、PDF、题文、维度来源说明与学习通模板的非MIT边界见 [SOURCES.md](SOURCES.md)。
