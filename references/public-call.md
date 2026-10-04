# 公共调用说明

适用于已加载本Skill的宿主模型；自然语言理解留在宿主，程序仅接受确定性参数。不要实现或调用另一套题库、模型API或问卷星服务。

## 路径、解释器与参数

实际根目录是宿主本次加载的`SKILL.md`所在目录，包含`scripts`、`data`和`docs`；不要把工作目录、开发机路径或未经宿主确认的占位符当作根目录。解释器使用宿主执行工具中已经可用的Python 3.10+，可先用参数数组执行`--version`确认。可执行文件名是`python`、`python3`或绝对解释器路径中的哪一个，依环境确定，不安装或切换全局环境。

优先调用宿主有依据的进程工具，分别传可执行文件和参数数组。Python环境内使用`subprocess.run([...], shell=False, ...)`；PowerShell使用`& $pythonPath @arguments`。课程、场景、请求ID、输出路径始终作为一个参数元素，不用字符串拼接、`Invoke-Expression`、`cmd /c`或`shell=True`。带换行或题型标记的无效参数由程序拒绝，不重试为可执行代码。

如下Python调用示例中的`skill_root`、`python_path`和业务变量由宿主从实际加载位置、解释器和用户需求分别确定，不是宿主协议字段：

```python
import json
from pathlib import Path
import subprocess

script = Path(skill_root) / "scripts" / "survey_export.py"
arguments = [python_path, "-B", str(script), "--project", project_id]
for flag, value in [("--version", version_id), ("--course", course),
                    ("--scenario", scenario), ("--output-dir", output_dir),
                    ("--request-id", request_id)]:
    if value is not None:
        arguments.extend([flag, value])
process = subprocess.run(arguments, shell=False, capture_output=True,
                         text=True, encoding="utf-8")
result = json.loads(process.stdout)
```

这些调用从任意当前目录可执行，资源按脚本位置定位，中文路径可用。`output_dir=None`时不传该参数，默认实际Skill根目录下`output`；用户明确提供相对输出路径时它相对执行工具的实际cwd，回复时使用返回的绝对路径。空字符串不等于省略。目录不可写时报告`OUTPUT_WRITE_FAILED`并让用户选可写位置，不能报告成功或自动改全局权限。

## 查询与完整导出

| 操作 | 脚本及参数 | 用途 |
| --- | --- | --- |
| 可用项目 | survey_data.py list | 从正式catalog取得全部项目、准确别名、真实版本和来源数据状态 |
| 项目核实 | survey_data.py find 项目名称或ID | 使用提取出的项目概念，不能传整句自然语言 |
| 版本读取 | survey_data.py read 项目ID --version A/B/original | 读取原始来源及用途；不根据来源历史阻断字段自行判断当前呈现不可导出 |
| 全库校验 | survey_data.py validate | 校验索引、结构、来源PDF哈希及原审核状态 |
| 完整生成 | survey_export.py --project 项目ID [--version 版本] [--course 课程] [--scenario 场景] [--output-dir 目录] [--request-id 标识] | 公共准备层应用有效规则，再渲染、校验、事务写出三文件包 |

`survey_data.py --request-id 标识`位于子命令前；`survey_export.py`请求ID是普通选项。单版本允许不传版本，程序选择唯一来源；为便于追踪也可使用查询确认的`original`。多版本不传时返回`VERSION_REQUIRED`，不要自行选择首卷或按前后测指定卷。A/B是否适合用户的具体课程用途，不能从卷名字母推断。

正式来源数据保留历史未知/阻断及`eligible_for_generation=false`；有效呈现规则在准备层解决用户已批准的问题。当前导出资格由公共导出程序评估，不能只见catalog旧状态就拒绝全部第一辑或工程伦理，也不能绕过程序中真正未解的阻断。

不要在日常生成使用`--source-item-id`，该参数仅用于人工导入测试子集。批量16版交付可使用`survey_delivery.py`，但用户要求一份问卷时只导出指定项目及版本，不组合或批量生成。

## 请求理解的决策

- “学生创造力”可识别为请求针对学生的“创造力”项目，必须通过catalog核实，不需要把整句或“学生”前缀追加成新的项目别名。
- “用于Python课程前测”提取`course=Python课程`、`scenario=前测`；仅用于标题。没有这两个可选参数就直接导出。
- “批判性思维前测”核实存在A/B后只询问选择哪卷；“批判性思维B卷……后测”使用明确B卷。不要让“前测/后测”替代版本选择。
- 概念相关但不是已确认项目别名时，查实际目录并说明候选，请用户选择。未收录项目不编制量规。
- 学生核心素养原卷指导语涉及“指标合理性”的评价。用户明确要求用于个人能力测量时先说明差异，不擅自更改指导语或直接生成供该目的使用；需要用户明确接受原用途后再导出。

## 结果与文件返回

公共JSON信封是`schema_version=1.0`、`skill_id=kcsz-course-survey`、`workflow=teaching`；`summary.content.operation`区分list/find/read/validate/export，业务内容在`summary.content.data`。检查进程退出码与`ok`一致，不只看stdout存在。

成功导出`artifacts`包含`primary`（UTF-8 TXT）、`teacher`（教师说明）、`mapping`（manifest）。读取真实`path`，确认是实际文件、UTF-8可读，并核对manifest的项目/版本、TXT SHA-256及题量。附件功能由具体宿主提供：使用真实文件附件API或实际本地文件入口；没有附件API时返回完整绝对路径，不能自造URL。返回主TXT，教师/来源材料简短附后。

导出核心每次建立唯一目录，重复请求不覆盖旧文件；失败不返回可用的正式TXT。完整例子：“已生成创造力原版，用于Python课程前测。该版此前获用户反馈导入通过；本次文件已生成，请自行导入问卷星。”其余未反馈版本写“待用户逐版导入验证”。具体证据范围见[导入反馈](import-feedback.md)，不能称平台自动验证或宿主运行通过。

| 退出码／错误 | 处理 |
| --- | --- |
| 0 且ok=true | 操作完成；确认文件后交付，不自动宣称平台导入通过 |
| 2／VERSION_REQUIRED | 根据真实candidates简短询问版本，不自动重试首卷 |
| 2／AMBIGUOUS_PROJECT | 展示真实候选项目ID与名称，请用户选择 |
| 2／PROJECT_NOT_FOUND、VERSION_NOT_FOUND | 说明未收录／版本不存在及真实候选，不编题 |
| 2／INVALID_REQUEST | 明确哪个参数不合法；不将参数转作Shell代码 |
| 4／INVALID_DATA、PRESENTATION_BLOCKED、TARGET_FORMAT_LIMIT | 说明具体问题及受影响题目；不隐藏或忽略错误生成 |
| 5／OUTPUT_WRITE_FAILED | 报告输出失败及路径问题；不交付.partial或旧文件冒充本轮成功 |

`model_trace=[]`只说明Python核心不调用模型；宿主当前模型仍负责理解、版本追问和调度。无需新增或配置模型Key、问卷星Key。
