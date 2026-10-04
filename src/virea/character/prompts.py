"""Wire descriptions for model outputs; personality lives in session preferences."""

DECISION_RULES = """当前任务是把本轮回应计划表达成一轮完整的口头回复。
角色设定描述说话者，历史记录描述已经发生的对话，Current state 提供当前可用能力。
reply_plan 是本轮内容计划；有 utterances 时，每项意图按原顺序实现为一个 beat，继承它的 start；没有时按 outline 组织完整回应。
每个 beat 的 text 是将被朗读的正文，motion_intent 是同期身体手势的中文运动描述。
start 是这段话的执行依赖：immediate 可独立发言，body_start/end 对应整项活动开始/完成，objective_start/end 对应已采纳目标的实际进度。结合话语用途、原始请求和现场状态规划，不把准备好等同于已完成；没有依赖的交流可以立即进行。
SPEAK 表示发言，WAIT 表示用户此时希望保持安静；actions 是实际可执行的场景操作。
JSON 按 schema 序列化，控制字段在 beats 之前，以便正文完成前开始流式播放。
"""
