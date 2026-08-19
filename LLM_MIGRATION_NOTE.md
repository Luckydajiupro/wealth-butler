# LLM模型切换说明（QwenLlm → DeepSeek）

## 重要变更

### 功能限制
DeepSeek模型**不支持**以下Qwen特有功能：
1. **OCR（图片识别）** - `llm.ocr()`
2. **ASR（语音识别）** - `llm.asr()`  
3. **Embedding（向量化）** - `llm.embedding()`

### 受影响的功能模块

#### 1. 向量搜索功能（已临时禁用）
**文件**: `app/Base/Service/aiService.py`
- `rewrite_question()` 方法中的向量相似度搜索已禁用
- 当前使用空列表替代向量搜索结果
- **恢复方案**: 需要单独配置Ollama或其他embedding模型

#### 2. 关键词向量化（需要外部方案）
**文件**: `app/Base/Service/keywordService.py:55`
- `sync_active_keywords_to_vdb()` 方法调用了 `llm.embedding()`
- **恢复方案**: 使用Ollama的bge-m3模型或其他embedding服务

### 环境变量配置

确保`.env`文件中包含以下DeepSeek配置：
```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_DEFAULT_MODEL=deepseek-chat
```

### 后续优化建议

1. **向量化服务解耦**
   - 将embedding功能从LLM中分离
   - 统一使用Ollama的bge-m3模型处理向量化需求
   - 修改 `keywordService` 和 `aiService` 使用独立的embedding客户端

2. **功能降级策略**
   - OCR功能：考虑接入百度/腾讯云OCR服务
   - ASR功能：考虑接入阿里云/科大讯飞语音服务
   - Embedding：使用本地Ollama模型

3. **混合模式支持**
   - 保留QwenLlm用于OCR/ASR/Embedding场景
   - DeepSeek用于对话和推理场景
   - 在BaseAgent中支持多LLM协同工作

### 验证清单

- [x] 所有Agent导入DeepSeek LLM
- [x] 对话服务使用DeepSeek
- [x] 数据库服务层切换完成
- [ ] 向量化功能恢复（需要配置Ollama）
- [ ] OCR/ASR功能评估（如果项目需要）
- [ ] 生产环境性能测试

---
**迁移时间**: 2026-08-16  
**执行人**: Claude Code Agent
