# 训练数据的规矩（写死在代码里）

这里的数据以后用来训练小脑和决策脑。只放这几种：
- 你自己发的消息、你的纠正
- DeepSeek 的处理记录（DeepSeek 官方明确允许用它的输出训练其他模型）
- 本地模型自己的输出

**不放任何 Claude 的输出**：网页 Claude 的回答、带回的总结、和 Claude 的聊天记录都不行，
回答时参考过 Claude 内容的 DeepSeek 记录也不存。
原因：Anthropic 的用户条款不允许用 Claude 的服务去开发或训练 AI 模型。Claude 的总结只放在 memory\总结，当参考资料读。
