# 课程思政问卷助手

`kcsz-course-survey` 按教师选择的价值目标组织问卷，导出问卷星 UTF-8 TXT 或学习通 Excel（`.xls`），同时提供教师说明和来源映射。当前软件版本为 **v0.2.0-rc.1 预发布版**，见 [VERSION](VERSION)。

- [GitHub 源码](https://github.com/awei0728/kcsz-course-survey)
- [v0.2.0-rc.1 发布页](https://github.com/awei0728/kcsz-course-survey/releases/tag/v0.2.0-rc.1)
- [完整 Skill 安装 ZIP](https://github.com/awei0728/kcsz-course-survey/releases/download/v0.2.0-rc.1/kcsz-course-survey-v0.2.0-rc.1-workbuddy.zip)

软件预发布与题库施测许可分别管理。当前482道题仍为研究候选，默认输出候选审查稿；选入、抽样或发布软件均不提升题目的正式施测许可。实际导入问卷星、学习通及当次宿主运行结果须分别验证。

## 三个维度与18个价值目标

新版数据层保留 **482道候选题、505条来源记录、188道核心候选和294道备份候选**，23个候选各对应两个来源。原始30字段、项目内维度和题文、分库、合并、计分、量尺五类确认独立保留。

| 一级组织维度 | 项目数 | 价值目标 |
| --- | ---: | --- |
| 家国认同 | 3 | 爱国主义态度、中华文化传播意愿、对华友好态度 |
| 文化涵养 | 9 | 批判性思维、学生核心素养、科学精神、创造力、思考方式和问题解决能力、文化认同、跨文化理解、中华文化认知与理解、生命敬畏态度 |
| 职业素养 | 6 | 学习自我效能感、专业认同感、学习风格和学习投入度、合作和社交能力、工程伦理、科研诚信意识 |

一级维度用于导航和组卷上限，不替代项目内部的原始维度，也不表示已验证的统一三因子量表。每项目只有一个主归属，关联维度不重复计数；配置见 [dimensions.json](data/candidates/dimensions.json)。

## 选题规则

| 模式 | 未指定题数 | 指定题数 |
| --- | --- | --- |
| 单目标 | 该项目全部核心＋备份候选 | 从两库合并池等概率、无放回抽取，不优先核心 |
| 多目标 | 各目标全部核心候选 | 仅从核心池抽取，按目标尽量均衡分配 |

多目标最多6个，同一主归属维度最多3个。指定数量是**整份问卷总题数**，不能超过可用题数；多目标至少每个目标1题。容量不足的目标停止分配，其余份额转给仍有候选的目标。抽题默认种子为0，可指定种子复现或更换结果，展示仍按原题顺序。

示例：创造力单目标默认12题（6核心＋6备份）；爱国主义态度＋创造力＋学习自我效能感默认22题，指定10题时分配为4＋3＋3，全部核心。详细接口见 [18目标组卷](references/candidate-surveys.md)。

## 两种导出格式

| 主文件 | 格式与用途 |
| --- | --- |
| `questionnaire.txt` | 问卷星文本导入；每题五级单选，连续编号、每个选项独占一行 |
| `questionnaire.xls` | 真正的 Excel 97–2003 BIFF8 文件；沿用户学习通模板20列，每题一行“测评题”，正确答案留空，5个选项 |
| `teacher-notes.md` | 实际选题数量、抽题规则、各目标分配、风险与教师审查状态 |
| `manifest.json` | 候选ID、来源与教师事件、原始字段、五类确认、选题种子与主文件SHA-256 |

每次导出创建独立目录，不覆盖已有问卷。默认在实际 Skill 根目录 `output/candidates/` 下，也可指定可写的 `--output-dir`。宿主应以 `artifacts[].path` 返回真实文件，不能推测文件位置或编造下载链接。

学习通不添加正确答案、考试得分或反向公式。程序不在线创建问卷、不处理答卷、不自动计分、不生成未验证的等级或阈值。统一五级同意是候选工作方案，不能推定与原量尺等值；科研诚信历史双量尺冲突仍保留，不由组卷程序自动解决。

## 在 TeachClaw 使用

新版固定命令默认使用18目标候选流程，无需为候选选择A/B卷。示例：

```text
生成课程思政调查问卷 --创造力
生成课程思政调查问卷 --创造力 --题数 8 --格式 问卷星
生成课程思政调查问卷 --爱国主义态度 --创造力 --学习自我效能感 --题数 10 --格式 学习通
```

默认格式为问卷星；`--格式`也可用`--format wjx|chaoxing`，`--题数`也可用`--question-count`。指定题数时可加`--种子`或`--seed`，不单独使用种子。明确指定`--原版`、`--source`或`--版本/--version`才走保留的旧来源版；旧来源版仅支持单项目问卷星，不混用候选题数或学习通格式。

TeachClaw接入由monorepo中的宿主插件负责，Skill安装ZIP不会自行安装、修改QQ账号或发送消息。部署与当次收件结果应分别留证；详见 [TeachClaw说明](references/teach-claw.md)。本发布构建的宿主实测状态独立记录，不将本地协议测试称为QQ实际收件。

本次已完成TeachClaw挂载、插件1.4.0升级及真实WSL systemd到Windows Runner验收，三维指定10题的TXT/XLS选题一致，单目标批判性思维默认41题。三附件回调采用本地模拟，真实QQ收件和问卷平台导入仍待用户反馈，见[发布验收记录](references/release-verification-v0.2.0-rc.1.md)。

## 在 WorkBuddy 安装

从本版发布页取得完整ZIP，在“技能→添加技能→上传技能”导入并启用，然后在 Craft 任务中选择该技能。保留包内 `kcsz-course-survey/SKILL.md` 层级，不只上传入口文件。具体流程依据及验证边界见 [WorkBuddy说明](references/workbuddy.md)。

可使用自然语言：

```text
生成创造力问卷，选8题，输出问卷星文本。
从三个维度各选一个目标：爱国主义态度、创造力、学习自我效能感，共10题，输出学习通Excel。
有哪些价值目标可以选择？
```

此前包的WorkBuddy加载与创造力生成曾获用户反馈通过，不能扩张为本新版重新加载已通过。

## Python独立调用

运行核心只使用 **Python 3.10+ 标准库** 和本目录模块，不需要模型Key、问卷星Key、Gateway或OpenClaw服务。当前主开发检查使用Python3.14.7；旧版另有Python3.12.14验证记录，最低3.10未单独实测。宿主自然语言理解沿用其已有模型。

从实际Skill根目录运行，或传入脚本绝对路径；所有用户参数作为独立argv传递，不拼接成Shell代码：

```powershell
python -B scripts/candidate_data.py validate
python -B scripts/candidate_survey.py --list
python -B scripts/candidate_survey.py --goal '创造力' --question-count 8 --format wjx
python -B scripts/candidate_survey.py --goal '爱国主义态度' --goal '创造力' --goal '学习自我效能感' --question-count 10 --format chaoxing
```

`survey_export.py`和`teachclaw_entry.py`的`--goal`、`--format`、`--question-count`也可进入候选流程。为了兼容已有调用，不带候选参数的旧Python `--project/--version`接口继续按来源版导出；TeachClaw插件会显式传候选参数，默认固定命令因此使用新版。

程序返回UTF-8 JSON。退出码0表示本地完成，2表示请求/选择错误，4表示数据/呈现/施测守门错误，5表示输出失败。检查 `ok/error/artifacts` 后再交付文件；`model_trace=[]`只表示核心未调用模型。资源与移位运行要求见 [runtime.md](references/runtime.md)。

## 保留的12项目、16来源版本

旧来源目录 [catalog.json](data/catalog.json) 和16份来源JSON保持独立，保留原题、原选项、尺度与明确分组。明确要求原版/A卷/B卷时使用它们，不将其与18目标改编候选混用。前测、后测不自动对应A/B卷。

```powershell
python -B scripts/survey_data.py validate
python -B scripts/survey_export.py --project critical-thinking --version B
python -B scripts/survey_export.py --project creativity --course 'Python课程' --scenario '前测'
```

学生核心素养原卷评价指标合理性，不能直接解释成学生个人能力自评。工程伦理旧来源版维持作答规则补全与基础题型适配：11道作答题、19个字段，第3、4题用独立参考说明、【代码】、中文逗号及普通填空；排序合法性和“其他”说明由教师核对。

历史问卷星实际导入反馈仅覆盖创造力原版及工程伦理修正版2版，其余14版待逐版反馈。本版候选TXT/XLS的本地生成、结构检查和Excel读取成功，均不等于目标平台实际导入通过。详细历史见 [验证与反馈](references/import-feedback.md)。

## 发布与来源

本软件采用白名单构建，GitHub安装ZIP、manifest、SHA256SUMS和发布说明均可独立核验，见 [BUILDING.md](BUILDING.md) 与 [RELEASE_NOTES.md](RELEASE_NOTES.md)。`v0.1.0-rc.1`保留为历史版本，不覆盖其标签或附件。

原创代码、测试及原创操作说明采用 [MIT](LICENSE)。两份指南PDF、量规原文、候选交接材料、上传的维度说明和学习通模板及其中来源内容不因软件发布而获得MIT授权，保留原权利和来源，详见 [SOURCES.md](SOURCES.md)。
