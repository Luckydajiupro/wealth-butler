/**
 * AI助手通用模块
 *
 * 功能：
 * - 统一的SSE流式对话接口
 * - 多Agent类型支持（advisor/customer/analyst/operator/risk）
 * - 自动会话管理
 * - 错误处理和重试
 */

class AIAssistant {
    constructor(options = {}) {
        this.apiBase = options.apiBase || window.location.origin;
        this.agentType = options.agentType || 'advisor';
        this.conversationId = options.conversationId || `chat_${this.agentType}_${Date.now()}`;
        this.customerId = options.customerId || null;
        this.onMessage = options.onMessage || function() {};
        this.onError = options.onError || function() {};
        this.onComplete = options.onComplete || function() {};
    }

    /**
     * 发送消息（SSE流式接收）
     * @param {string} message - 用户消息
     * @returns {Promise<void>}
     */
    async sendMessage(message) {
        const token = localStorage.getItem('access_token');

        if (!token) {
            this.onError('未登录，请先登录');
            return;
        }

        try {
            const response = await fetch(`${this.apiBase}/api/wealth/chat`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    message: message,
                    agent_type: this.agentType,
                    conversation_id: this.conversationId,
                    customer_id: this.customerId
                })
            });

            if (!response.ok) {
                this.onError(`服务器错误: ${response.status}`);
                this.onComplete();
                return;
            }

            // 处理SSE流式响应
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();

                if (done) {
                    this.onComplete();
                    break;
                }

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');

                // 保留最后一个不完整的行
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6).trim();
                        if (data) {
                            try {
                                // 尝试解析JSON（错误消息或结构化数据）
                                const json = JSON.parse(data);
                                if (json.type === 'error') {
                                    this.onError(json.content);
                                } else {
                                    this.onMessage(json.content || data);
                                }
                            } catch {
                                // 普通文本内容，直接传递
                                this.onMessage(data);
                            }
                        }
                    }
                }
            }
        } catch (error) {
            console.error('AI助手请求失败:', error);
            this.onError('网络连接失败，请稍后重试');
            this.onComplete();
        }
    }

    /**
     * 切换Agent类型
     * @param {string} agentType - 新的Agent类型
     */
    switchAgent(agentType) {
        this.agentType = agentType;
        this.conversationId = `chat_${agentType}_${Date.now()}`;
    }

    /**
     * 设置客户ID
     * @param {number} customerId - 客户ID
     */
    setCustomer(customerId) {
        this.customerId = customerId;
    }
}

/**
 * 创建简单的聊天UI（浮动气泡）
 *
 * 使用示例：
 * const chat = createSimpleChatUI({
 *     agentType: 'advisor',
 *     containerId: 'aiAssistantContainer'
 * });
 */
function createSimpleChatUI(options = {}) {
    const agentType = options.agentType || 'advisor';
    const containerId = options.containerId || 'aiAssistantBubble';
    const agentName = options.agentName || 'AI助手';

    // 获取或创建容器
    let container = document.getElementById(containerId);
    if (!container) {
        container = document.createElement('div');
        container.id = containerId;
        document.body.appendChild(container);
    }

    // 注入HTML
    container.innerHTML = `
        <div class="ai-bubble-trigger" id="aiBubbleTrigger">🤖</div>
        <div class="ai-chat-window" id="aiChatWindow">
            <div class="ai-chat-header">
                <span class="ai-chat-title">${agentName}</span>
                <button class="ai-chat-close" id="aiChatClose">×</button>
            </div>
            <div class="ai-chat-messages" id="aiChatMessages"></div>
            <div class="ai-chat-input-area">
                <textarea class="ai-chat-input" id="aiChatInput" placeholder="输入您的问题..." rows="2"></textarea>
                <button class="ai-chat-send-btn" id="aiChatSendBtn">发送</button>
            </div>
        </div>
    `;

    // 注入CSS
    if (!document.getElementById('aiAssistantStyles')) {
        const style = document.createElement('style');
        style.id = 'aiAssistantStyles';
        style.textContent = `
            .ai-bubble-trigger {
                position: fixed;
                bottom: 30px;
                right: 30px;
                width: 60px;
                height: 60px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 28px;
                cursor: pointer;
                box-shadow: 0 4px 20px rgba(102, 126, 234, 0.4);
                transition: transform 0.2s;
                z-index: 1000;
            }
            .ai-bubble-trigger:hover {
                transform: scale(1.1);
            }
            .ai-chat-window {
                position: fixed;
                bottom: 100px;
                right: 30px;
                width: 400px;
                height: 600px;
                background: white;
                border-radius: 16px;
                box-shadow: 0 8px 40px rgba(0, 0, 0, 0.15);
                display: none;
                flex-direction: column;
                overflow: hidden;
                z-index: 1001;
            }
            .ai-chat-window.show {
                display: flex;
            }
            .ai-chat-header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 16px;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }
            .ai-chat-title {
                font-size: 16px;
                font-weight: 600;
            }
            .ai-chat-close {
                width: 28px;
                height: 28px;
                background: rgba(255, 255, 255, 0.2);
                border: none;
                border-radius: 50%;
                color: white;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 20px;
                transition: background 0.2s;
            }
            .ai-chat-close:hover {
                background: rgba(255, 255, 255, 0.3);
            }
            .ai-chat-messages {
                flex: 1;
                padding: 20px;
                overflow-y: auto;
                background: #f9fafb;
            }
            .ai-message {
                margin-bottom: 16px;
                display: flex;
                gap: 10px;
            }
            .ai-message.user {
                flex-direction: row-reverse;
            }
            .ai-message-avatar {
                width: 32px;
                height: 32px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
                font-size: 14px;
            }
            .ai-message.assistant .ai-message-avatar {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .ai-message.user .ai-message-avatar {
                background: #e0e0e0;
                color: #666;
            }
            .ai-message-content {
                max-width: 70%;
                padding: 12px 16px;
                border-radius: 12px;
                font-size: 14px;
                line-height: 1.5;
                white-space: pre-wrap;
                word-wrap: break-word;
            }
            .ai-message.assistant .ai-message-content {
                background: white;
                color: #333;
            }
            .ai-message.user .ai-message-content {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .ai-chat-input-area {
                padding: 16px;
                background: white;
                border-top: 1px solid #e0e0e0;
            }
            .ai-chat-input {
                width: 100%;
                padding: 12px;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                font-size: 14px;
                resize: none;
                font-family: inherit;
                outline: none;
                transition: border-color 0.2s;
            }
            .ai-chat-input:focus {
                border-color: #667eea;
            }
            .ai-chat-send-btn {
                width: 100%;
                padding: 10px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 500;
                cursor: pointer;
                margin-top: 8px;
                transition: transform 0.2s;
            }
            .ai-chat-send-btn:hover {
                transform: translateY(-1px);
            }
            .ai-chat-send-btn:disabled {
                opacity: 0.6;
                cursor: not-allowed;
                transform: none;
            }
        `;
        document.head.appendChild(style);
    }

    // 初始化AI助手
    const assistant = new AIAssistant({
        agentType: agentType,
        conversationId: `${options.conversationId || agentType}_${Date.now()}`,
        customerId: options.customerId,
        onMessage: (chunk) => {
            appendToLastMessage(chunk);
        },
        onError: (error) => {
            addMessage('assistant', `抱歉，出现错误：${error}`);
        },
        onComplete: () => {
            document.getElementById('aiChatSendBtn').disabled = false;
        }
    });

    // 消息历史
    const messages = [];

    // 添加消息到历史
    function addMessage(role, content) {
        messages.push({ role, content });
        renderMessages();
    }

    // 追加内容到最后一条消息
    function appendToLastMessage(chunk) {
        if (messages.length > 0 && messages[messages.length - 1].role === 'assistant') {
            messages[messages.length - 1].content += chunk;
        } else {
            messages.push({ role: 'assistant', content: chunk });
        }
        renderMessages();
    }

    // 渲染消息列表
    function renderMessages() {
        const messagesContainer = document.getElementById('aiChatMessages');
        messagesContainer.innerHTML = messages.map(msg => {
            const avatarText = msg.role === 'user' ? '我' : '🤖';
            return `
                <div class="ai-message ${msg.role}">
                    <div class="ai-message-avatar">${avatarText}</div>
                    <div class="ai-message-content">${escapeHtml(msg.content)}</div>
                </div>
            `;
        }).join('');
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    // HTML转义
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // 发送消息
    async function sendMessage() {
        const input = document.getElementById('aiChatInput');
        const sendBtn = document.getElementById('aiChatSendBtn');
        const message = input.value.trim();

        if (!message) return;

        // 添加用户消息
        addMessage('user', message);
        input.value = '';
        sendBtn.disabled = true;

        // 发送到AI助手
        await assistant.sendMessage(message);
    }

    // 绑定事件
    document.getElementById('aiBubbleTrigger').addEventListener('click', () => {
        const chatWindow = document.getElementById('aiChatWindow');
        chatWindow.classList.toggle('show');

        // 首次打开时显示欢迎消息
        if (chatWindow.classList.contains('show') && messages.length === 0) {
            addMessage('assistant', `您好！我是${agentName}，很高兴为您服务。请问有什么可以帮您的？`);
        }
    });

    document.getElementById('aiChatClose').addEventListener('click', () => {
        document.getElementById('aiChatWindow').classList.remove('show');
    });

    document.getElementById('aiChatSendBtn').addEventListener('click', sendMessage);

    document.getElementById('aiChatInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    return {
        assistant,
        addMessage,
        show: () => document.getElementById('aiChatWindow').classList.add('show'),
        hide: () => document.getElementById('aiChatWindow').classList.remove('show')
    };
}

// 导出到全局
if (typeof window !== 'undefined') {
    window.AIAssistant = AIAssistant;
    window.createSimpleChatUI = createSimpleChatUI;
}
