import { useEffect, useState } from 'react'
import './App.css'

// 示例问题卡片（空状态引导：让店长一眼知道"能问什么"）
const EXAMPLE_QUESTIONS = [
  { label: '销量排行', question: '这个月销量最好的 5 款饮品是什么？' },
  { label: '毛利分析', question: '毛利最高的饮品是哪款？' },
  { label: '备货建议', question: '下周天气怎么样？根据天气和销量规律，我该多备什么货？' },
  { label: '会员洞察', question: '会员平均消费多少钱？复购过的会员有多少？' },
  { label: '疫情数据', question: '美国最近 30 天疫情确诊趋势怎么样？' },
]

// 能力披露（告诉店长边界，降低预期）
const CAPABILITIES = [
  '用大白话查询经营数据（销量 / 毛利 / 会员）',
  '结合天气预报和历史销量，辅助分析备货',
  '查询全球疫情数据（国家现状 / 历史趋势）',
  '自动拆解复杂问题、多数据源协同分析',
]

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [freshness, setFreshness] = useState(null) // 数据新鲜度
  const [authOpen, setAuthOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyItems, setHistoryItems] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [token, setToken] = useState(() => localStorage.getItem('cafe_auth_token') || '')
  const [currentUser, setCurrentUser] = useState(null)
  const [bottomNode, setBottomNode] = useState(null)

  // 匿名会话标识：一次浏览器会话内固定，让多轮追问能记住上下文
  const [sessionId] = useState(() => {
    const existing = localStorage.getItem('cafe_session_id')
    const value = existing || crypto.randomUUID()
    localStorage.setItem('cafe_session_id', value)
    return value
  })

  // 自动滚动到底部
  useEffect(() => {
    bottomNode?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, bottomNode])

  // 用已保存的 Token 恢复登录状态；失效 Token 会被清理。
  useEffect(() => {
    if (!token) {
      return
    }
    fetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((resp) => {
        if (!resp.ok) throw new Error('登录已过期')
        return resp.json()
      })
      .then(setCurrentUser)
      .catch(() => {
        localStorage.removeItem('cafe_auth_token')
        setToken('')
        setCurrentUser(null)
      })
  }, [token])

  // 启动时拉取数据新鲜度（能力披露的一部分）
  useEffect(() => {
    fetch('/api/datasource/freshness')
      .then((r) => r.json())
      .then((d) => setFreshness(d))
      .catch(() => {})
  }, [])

  const send = async (q) => {
    const question = (q ?? input).trim()
    if (!question || loading) return

    setInput('')
    setLoading(true)
    setMessages((prev) => [...prev, { role: 'user', text: question }])
    setMessages((prev) => [...prev, { role: 'assistant', steps: [], sqls: [], answer: '', chart: null, status: '分析中...' }])

    try {
      const resp = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ question, session_id: sessionId }),
      })

      if (!resp.ok) {
        throw new Error(`请求失败（HTTP ${resp.status}）`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop()
        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data:')) continue
          const data = JSON.parse(line.slice(5).trim())
          handleEvent(data)
        }
      }
    } catch (err) {
      updateAssistant((prev) => ({ ...prev, status: '出错：' + err.message }))
    } finally {
      setLoading(false)
    }
  }

  const handleEvent = (data) => {
    switch (data.type) {
      case 'intent':
        updateAssistant((prev) => ({ ...prev, status: data.intent === 'chat' ? '思考中...' : '规划中...' }))
        break
      case 'planner':
        updateAssistant((prev) => ({ ...prev, steps: data.steps || [], status: '规划完成，开始逐步查询...' }))
        break
      case 'executor':
        updateAssistant((prev) => ({
          ...prev,
          status: `正在执行第 ${data.step} 步...`,
          sqls: [...prev.sqls, { step: data.step, sql: data.sql, rows: data.rows, columns: data.columns, error: data.error }],
        }))
        break
      case 'answer':
        // 闲聊链路：直接回答
        updateAssistant((prev) => ({ ...prev, answer: data.answer || '', status: '完成' }))
        break
      case 'summary':
        updateAssistant((prev) => ({ ...prev, answer: data.answer || '', status: '分析完成' }))
        break
      case 'clarify':
        // 信息不足，后端反问：把反问问题当作助手回答展示，引导用户补充
        updateAssistant((prev) => ({ ...prev, answer: data.question || data.message || '', status: '需要补充信息' }))
        break
      case 'chart':
        // 后端判断结果可出图 → 前端画图
        updateAssistant((prev) => ({ ...prev, chart: data.chart || null }))
        break
      case 'done':
        updateAssistant((prev) => ({ ...prev, status: prev.answer ? '完成' : '完成' }))
        break
      case 'error':
        updateAssistant((prev) => ({ ...prev, status: '出错：' + data.message }))
        break
      default:
        break
    }
  }

  const updateAssistant = (updater) => {
    setMessages((prev) => {
      const next = [...prev]
      const last = next[next.length - 1]
      if (last && last.role === 'assistant') {
        next[next.length - 1] = updater(last)
      }
      return next
    })
  }

  const handleAuthenticated = (accessToken, username) => {
    localStorage.setItem('cafe_auth_token', accessToken)
    setToken(accessToken)
    setCurrentUser({ username })
    setAuthOpen(false)
  }

  const logout = () => {
    localStorage.removeItem('cafe_auth_token')
    setToken('')
    setCurrentUser(null)
    setHistoryItems([])
    setHistoryOpen(false)
  }

  const openHistory = async () => {
    if (!token) {
      setAuthOpen(true)
      return
    }
    setHistoryOpen(true)
    setHistoryLoading(true)
    try {
      const resp = await fetch('/api/history', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!resp.ok) throw new Error('无法读取历史记录')
      const data = await resp.json()
      setHistoryItems(data.items || [])
    } catch (err) {
      setHistoryItems([{ id: 'error', question: '读取失败', answer: err.message }])
    } finally {
      setHistoryLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>咖啡店经营助手</h1>
          <p>店长的数据副手：查销量、看毛利、结合天气辅助备货分析</p>
        </div>
        <div className="user-actions">
          <button className="ghost-button" onClick={openHistory}>
            历史记录
          </button>
          {currentUser ? (
            <>
              <span className="user-name">{currentUser.username}</span>
              <button className="ghost-button" onClick={logout}>退出</button>
            </>
          ) : (
            <button className="primary-button" onClick={() => setAuthOpen(true)}>登录</button>
          )}
        </div>
      </header>

      <div className="chat">
        {messages.length === 0 && (
          <div className="welcome">
            <div className="welcome-title">店长你好，今天想了解什么？</div>
            <div className="capabilities">
              {CAPABILITIES.map((c, i) => (
                <div key={i} className="cap-item">{c}</div>
              ))}
            </div>

            <div className="examples-title">试试这些问题：</div>
            <div className="examples">
              {EXAMPLE_QUESTIONS.map((e, i) => (
                <button key={i} className="example-card" onClick={() => send(e.question)}>
                  <div className="example-label">{e.label}</div>
                  <div className="example-q">{e.question}</div>
                </button>
              ))}
            </div>

            {freshness && (
              <div className="freshness">
                <div className="freshness-title">数据来源与新鲜度</div>
                {(freshness.sources || []).map((s, i) => (
                  <div key={i} className="freshness-item">
                    <span className={`freshness-dot ${s.status === 'ok' ? 'ok' : 'err'}`} />
                    <span className="freshness-label">{s.label}</span>
                    <span className="freshness-note">{s.note}</span>
                  </div>
                ))}
                <span className="freshness-disclaimer">（以上数据仅作演示参考，不构成经营建议）</span>
              </div>
            )}
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`msg ${msg.role}`}>
            {msg.role === 'user' ? (
              <div className="bubble user-bubble">{msg.text}</div>
            ) : (
              <div className="assistant-content">
                {msg.steps?.length > 0 && (
                  <div className="steps">
                    <div className="steps-title">规划步骤：</div>
                    {msg.steps.map((s, j) => (
                      <div key={j} className="step">第 {j + 1} 步：{s}</div>
                    ))}
                  </div>
                )}

                {msg.sqls?.map((s, j) => (
                  <div key={j} className="sql-block">
                    <div className="sql-title">第 {s.step} 步查询</div>
                    {s.sql && <pre className="sql">{s.sql}</pre>}
                    {s.rows && s.rows.length > 0 && (
                      <pre className="rows">{s.rows.map((r) => (Array.isArray(r) ? r.join('  |  ') : String(r))).join('\n')}</pre>
                    )}
                    {s.error && <div className="error">查询失败：{s.error}</div>}
                  </div>
                ))}

                {msg.chart && <Chart chart={msg.chart} />}

                {msg.answer && (
                  <div className="answer">
                    <div className={`answer-title${msg.status === '需要补充信息' ? ' clarify-title' : ''}`}>
                      {msg.status === '需要补充信息' ? '需要补充信息' : '分析结论'}
                    </div>
                    <div className="answer-text" dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.answer) }} />
                  </div>
                )}

                {msg.status && <div className="status">{msg.status}</div>}
              </div>
            )}
          </div>
        ))}
        <div ref={setBottomNode} />
      </div>

      <div className="input-bar">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
          placeholder="问点经营数据吧，比如：这个月销量最好的饮品是什么？"
          rows={2}
        />
        <button onClick={() => send()} disabled={loading}>
          {loading ? '分析中...' : '发送'}
        </button>
      </div>

      {authOpen && (
        <AuthModal
          onClose={() => setAuthOpen(false)}
          onAuthenticated={handleAuthenticated}
        />
      )}
      {historyOpen && (
        <HistoryModal
          items={historyItems}
          loading={historyLoading}
          onClose={() => setHistoryOpen(false)}
        />
      )}
    </div>
  )
}

function AuthModal({ onClose, onAuthenticated }) {
  const [mode, setMode] = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      if (mode === 'register') {
        const registered = await fetch('/api/auth/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        })
        if (!registered.ok) {
          const data = await registered.json().catch(() => ({}))
          throw new Error(data.detail || '注册失败')
        }
      }

      const loginBody = new URLSearchParams()
      loginBody.set('username', username)
      loginBody.set('password', password)
      const loggedIn = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: loginBody,
      })
      if (!loggedIn.ok) {
        const data = await loggedIn.json().catch(() => ({}))
        throw new Error(data.detail || '用户名或密码错误')
      }
      const data = await loggedIn.json()
      onAuthenticated(data.access_token, data.username)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal-card auth-card" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-heading">
          <div>
            <h2>{mode === 'login' ? '登录' : '注册'}</h2>
            <p>登录后，对话会绑定到你的账户，并可在其他设备查看历史。</p>
          </div>
          <button className="close-button" onClick={onClose} aria-label="关闭">×</button>
        </div>
        <form onSubmit={submit} className="auth-form">
          <label>
            用户名
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              minLength={3}
              maxLength={50}
              autoComplete="username"
              required
            />
          </label>
          <label>
            密码
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={8}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              required
            />
          </label>
          {error && <div className="form-error">{error}</div>}
          <button className="form-submit" disabled={submitting}>
            {submitting ? '处理中...' : mode === 'login' ? '登录' : '注册并登录'}
          </button>
        </form>
        <button
          className="mode-switch"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            setError('')
          }}
        >
          {mode === 'login' ? '没有账号？注册' : '已有账号？登录'}
        </button>
      </div>
    </div>
  )
}

function HistoryModal({ items, loading, onClose }) {
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal-card history-card" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-heading">
          <div>
            <h2>历史记录</h2>
            <p>仅展示当前账户的会话。</p>
          </div>
          <button className="close-button" onClick={onClose} aria-label="关闭">×</button>
        </div>
        {loading && <div className="history-empty">加载中...</div>}
        {!loading && items.length === 0 && (
          <div className="history-empty">还没有历史记录，先问一个问题吧。</div>
        )}
        <div className="history-list">
          {items.map((item) => (
            <article className="history-item" key={item.id}>
              <div className="history-question">{item.question}</div>
              <div className="history-answer">{item.answer || '尚未生成回答'}</div>
              {item.created_at && (
                <time>{new Date(item.created_at).toLocaleString()}</time>
              )}
            </article>
          ))}
        </div>
      </div>
    </div>
  )
}

// 轻量图表组件：不引第三方库，用 SVG 画折线图/柱状图，保证零依赖
function Chart({ chart }) {
  if (!chart) return null
  const { type, x, y, data } = chart

  if (type === 'line' && data?.length > 1) {
    return <LineChart data={data} xLabel={x} yLabel={y} />
  }
  if (type === 'bar' && data?.length > 0) {
    return <BarChart data={data} xLabel={x} yLabel={y} />
  }
  return null
}

function LineChart({ data, xLabel, yLabel }) {
  const W = 560, H = 280, pad = 40
  const values = data.map((d) => Number(d.value))
  const max = Math.max(...values), min = Math.min(...values)
  const range = max - min || 1
  const stepX = (W - pad * 2) / (data.length - 1)
  const points = data.map((d, i) => {
    const px = pad + i * stepX
    const py = H - pad - ((Number(d.value) - min) / range) * (H - pad * 2)
    return [px, py]
  })
  // x 轴标签抽样：数据点多时只显示首/中/尾，避免重叠
  const labelStep = Math.max(1, Math.floor(data.length / 6))

  return (
    <div className="chart">
      <div className="chart-title">{yLabel} 趋势</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg">
        <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#ddd" strokeWidth="1" />
        <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="#ddd" strokeWidth="1" />
        <polyline points={points.map((p) => p.join(',')).join(' ')} fill="none" stroke="#534ab7" strokeWidth="2" />
        {points.map((p, i) => (
          <circle key={i} cx={p[0]} cy={p[1]} r="2.5" fill="#534ab7" />
        ))}
        {data.map((d, i) => {
          if (i % labelStep !== 0 && i !== data.length - 1) return null
          return (
            <text key={`x${i}`} x={points[i][0]} y={H - pad + 16} textAnchor="middle" fontSize="9" fill="#999">
              {d.label}
            </text>
          )
        })}
        <text x={W - pad} y={H - pad - 10} textAnchor="end" fontSize="11" fill="#999">{xLabel}</text>
        <text x={pad - 8} y={H - pad} textAnchor="end" fontSize="11" fill="#999">{min}</text>
        <text x={pad - 8} y={pad + 4} textAnchor="end" fontSize="11" fill="#999">{max}</text>
      </svg>
    </div>
  )
}

function BarChart({ data, xLabel, yLabel }) {
  const W = 560, H = 280, pad = 40
  const max = Math.max(...data.map((d) => Number(d.value))) || 1
  const bw = (W - pad * 2) / data.length
  // label 过长时旋转，避免重叠
  const labelLen = Math.max(...data.map((d) => String(d.label).length))
  const rotate = data.length > 5 || labelLen > 4
  return (
    <div className="chart">
      <div className="chart-title">{yLabel} 对比 · {xLabel}</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg">
        <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#ddd" strokeWidth="1" />
        <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="#ddd" strokeWidth="1" />
        {data.map((d, i) => {
          const h = (Number(d.value) / max) * (H - pad * 2)
          const x = pad + i * bw + bw * 0.2
          const w = bw * 0.6
          const y = H - pad - h
          return (
            <g key={i}>
              <rect x={x} y={y} width={w} height={h} fill="#185fa5" rx="2" />
              <text x={x + w / 2} y={y - 4} textAnchor="middle" fontSize="11" fill="#333">{d.value}</text>
              <text
                x={x + w / 2}
                y={H - pad + 14}
                textAnchor={rotate ? 'end' : 'middle'}
                fontSize="10"
                fill="#666"
                transform={rotate ? `rotate(-40 ${x + w / 2} ${H - pad + 14})` : undefined}
              >
                {d.label}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

// 轻量 Markdown 渲染：把 LLM 报告里的 # 标题 / **加粗** / - 列表转成 HTML。
// 不引第三方库，只处理最常见的几种语法，足够展示分析报告。
function renderMarkdown(text) {
  if (!text) return ''
  const escapeHtml = (s) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  const lines = text.split('\n')
  const out = []
  let inList = false

  const closeList = () => {
    if (inList) {
      out.push('</ul>')
      inList = false
    }
  }

  for (const line of lines) {
    const trimmed = line.trim()

    // 标题
    const h = trimmed.match(/^(#{1,4})\s+(.*)$/)
    if (h) {
      closeList()
      const level = h[1].length
      out.push(`<h${level}>${inline(escapeHtml(h[2]))}</h${level}>`)
      continue
    }

    // 无序列表
    const li = trimmed.match(/^[-*•]\s+(.*)$/)
    if (li) {
      if (!inList) {
        out.push('<ul>')
        inList = true
      }
      out.push(`<li>${inline(escapeHtml(li[1]))}</li>`)
      continue
    }

    // 有序列表
    const oli = trimmed.match(/^\d+[.、]\s+(.*)$/)
    if (oli) {
      closeList()
      out.push(`<p class="md-li">${inline(escapeHtml(oli[1]))}</p>`)
      continue
    }

    // 空行
    if (trimmed === '') {
      closeList()
      continue
    }

    // 普通段落
    closeList()
    out.push(`<p>${inline(escapeHtml(trimmed))}</p>`)
  }
  closeList()
  return out.join('')
}

// 行内样式：**加粗**、`代码`
function inline(text) {
  return text
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
}

export default App
