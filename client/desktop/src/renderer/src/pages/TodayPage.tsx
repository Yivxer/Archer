import React from 'react'
import { BellOff, BellRing, Check, Eye, LoaderCircle, RefreshCw, ShieldCheck, VolumeX } from 'lucide-react'
import { setInitiativeDeliveryOptIn, setInitiativePresence, submitInitiativeFeedback } from '../adapters/localArcher'
import type { ArcherAdapter } from '../types'

export function TodayPage({
  data,
  onRefresh,
}: {
  data: ArcherAdapter
  onRefresh: () => Promise<void>
}) {
  const candidates = data.initiativeShadow.items
    .filter((item) => item.kind === 'thread_resume')
    .slice(0, 3)
  const throttleLabel = data.initiativeShadow.globalThrottleActive ? '降频中' : 'Shadow 观察中'
  const presenceLabel = data.initiativeShadow.presenceState === 'muted'
    ? '已静音'
    : data.initiativeShadow.presenceState === 'engaged'
      ? '活跃'
      : '休眠'
  const report = data.initiativeShadow.report
  const longTermReport = data.initiativeShadow.longTermReport
  const deliveryGate = data.initiativeShadow.deliveryGate
  const optIn = data.initiativeShadow.optIn
  const reviewPacket = data.initiativeShadow.reviewPacket
  const reviewLabel = report.readyForManualReview ? '可人工复核' : '继续观察'
  const recognitionPercent = Math.round(report.recognitionRate * 100)
  const longTermRecognitionPercent = Math.round(longTermReport.metrics.relevance.recognitionRate * 100)
  const tooFrequentPercent = Math.round(longTermReport.metrics.relevance.tooFrequentRate * 100)
  const [busy, setBusy] = React.useState('')
  const [notice, setNotice] = React.useState('')
  const canControl = data.status.adapter === 'local'

  async function sendFeedback(id: number, feedback: 'acknowledged' | 'too_frequent') {
    if (!canControl || busy) return
    setBusy(`${id}:${feedback}`)
    setNotice('')
    try {
      await submitInitiativeFeedback(id, feedback)
      await onRefresh()
      setNotice(feedback === 'acknowledged' ? '已记录认可' : '已降低主动频率')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '反馈保存失败')
    } finally {
      setBusy('')
    }
  }

  async function togglePresence() {
    if (!canControl || busy) return
    const state = data.initiativeShadow.presenceState === 'muted' ? 'idle' : 'muted'
    setBusy('presence')
    setNotice('')
    try {
      await setInitiativePresence(state)
      await onRefresh()
      setNotice(state === 'muted' ? '已静音主动候选' : '已恢复主动候选')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '在场状态更新失败')
    } finally {
      setBusy('')
    }
  }

  async function toggleOptIn() {
    if (!canControl || busy) return
    const enabled = !optIn.enabled
    setBusy('opt-in')
    setNotice('')
    try {
      await setInitiativeDeliveryOptIn(enabled)
      await onRefresh()
      setNotice(enabled ? '已记录显式授权' : '已撤回显式授权')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '授权状态更新失败')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="today-page">
      <header className="today-page-head">
        <div>
          <div className="today-kicker"><Eye size={15} /> Today</div>
          <h1>话题拾起候选</h1>
          <p>唯一 live slice；只在 Archer 内展示，不进入聊天，也不触发系统通知。</p>
        </div>
        <div className="today-head-actions">
          <span className="today-state"><ShieldCheck size={14} /> {throttleLabel}</span>
          <span className="today-state">{presenceLabel}</span>
          {canControl && (
            <button
              className="quiet-button icon-button"
              type="button"
              onClick={() => void togglePresence()}
              disabled={Boolean(busy)}
              aria-label={data.initiativeShadow.presenceState === 'muted' ? '恢复主动候选' : '静音主动候选'}
              title={data.initiativeShadow.presenceState === 'muted' ? '恢复主动候选' : '静音主动候选'}
            >
              {busy === 'presence' ? <LoaderCircle size={15} className="spin" /> : data.initiativeShadow.presenceState === 'muted' ? <BellRing size={15} /> : <BellOff size={15} />}
            </button>
          )}
          <button className="quiet-button" type="button" onClick={() => void onRefresh()}>
            <RefreshCw size={15} /> 刷新
          </button>
        </div>
      </header>

      <section className="today-validation" aria-label="Shadow 人工复核状态">
        <div className="today-section-head">
          <h2>人工复核状态</h2>
          <span>{reviewLabel}</span>
        </div>
        <div className="today-validation-grid">
          <div>
            <strong>{report.observationDays}</strong>
            <span>观察天数 / {report.thresholds.requiredDays}</span>
          </div>
          <div>
            <strong>{report.dailyAverage.toFixed(1)}</strong>
            <span>日均候选 / {report.thresholds.maxDailyAverage}</span>
          </div>
          <div>
            <strong>{report.feedbackCount}</strong>
            <span>反馈数 / {report.thresholds.minFeedback}</span>
          </div>
          <div>
            <strong>{recognitionPercent}%</strong>
            <span>认可率 / {Math.round(report.thresholds.minRecognitionRate * 100)}%</span>
          </div>
        </div>
        {report.reasons.length > 0 ? (
          <div className="today-validation-reasons">
            {report.reasons.slice(0, 3).map((reason) => (
              <span key={reason}>{formatReportReason(reason)}</span>
            ))}
          </div>
        ) : (
          <p className="today-validation-ready">已达到人工复核门槛，仍保持 Shadow，不会自动真发送。</p>
        )}
      </section>

      <section className="today-validation" aria-label="Shadow 长期验证快照">
        <div className="today-section-head">
          <h2>长期验证快照</h2>
          <span>{longTermReport.readyForDeliveryReview ? '待人工决策' : '只观察'}</span>
        </div>
        <div className="today-validation-grid">
          <div>
            <strong>{longTermReport.observedDays}</strong>
            <span>累计观察天数</span>
          </div>
          <div>
            <strong>{longTermReport.metrics.frequency.dailyAverage.toFixed(1)}</strong>
            <span>日均候选</span>
          </div>
          <div>
            <strong>{longTermRecognitionPercent}%</strong>
            <span>长期认可率</span>
          </div>
          <div>
            <strong>{longTermReport.metrics.continuity.threadResumeCount}</strong>
            <span>话题拾起</span>
          </div>
        </div>
        <p className="today-validation-ready">
          太频繁 {tooFrequentPercent}% · 峰值 {longTermReport.metrics.frequency.maxDailyCount} 条/日 · 只读快照，不会自动切真发送。
        </p>
      </section>

      <section className="today-validation" aria-label="Shadow 切真发送保险丝">
        <div className="today-section-head">
          <h2>话题拾起投递保险丝</h2>
          <span>{deliveryGate.shadowOnly ? 'Shadow 锁定' : '可人工开启'}</span>
        </div>
        <div className="today-validation-grid">
          <div>
            <strong>{deliveryGate.requirements.requiredObservationDays}</strong>
            <span>最低观察天数</span>
          </div>
          <div>
            <strong>{deliveryGate.requirements.manualReview ? '是' : '否'}</strong>
            <span>需要人工复核</span>
          </div>
          <div>
            <strong>{optIn.enabled ? '已授权' : '未授权'}</strong>
            <span>显式授权</span>
          </div>
          <div>
            <strong>{deliveryGate.canEnableDelivery ? '可' : '否'}</strong>
            <span>当前可真发送</span>
          </div>
        </div>
        <p className="today-validation-ready">
          复核建议：{formatReviewAction(reviewPacket.recommendedAction)} · 剩余观察 {deliveryGate.timeline.remainingObservationDays} 天 · 最早复核 {formatGateTime(deliveryGate.timeline.earliestReviewAt)}
        </p>
        {canControl && (
          <button
            className="quiet-button"
            type="button"
            onClick={() => void toggleOptIn()}
            disabled={Boolean(busy)}
          >
            {busy === 'opt-in' ? <LoaderCircle size={15} className="spin" /> : <ShieldCheck size={15} />}
            {optIn.enabled ? '关闭话题拾起' : '授权话题拾起'}
          </button>
        )}
        <div className="today-validation-reasons">
          {(deliveryGate.reasons.length ? deliveryGate.reasons : ['shadow_only']).slice(0, 3).map((reason) => (
            <span key={reason}>{formatGateReason(reason)}</span>
          ))}
        </div>
      </section>

      <section className="today-candidates" aria-label="今日主动候选">
        <div className="today-section-head">
          <h2>话题拾起候选</h2>
          <span>{candidates.length}</span>
        </div>
        {candidates.length ? (
          <div className="today-candidate-grid">
            {candidates.map((item) => (
              <article className="today-candidate-card" key={item.id}>
                <div className="today-candidate-head">
                  <strong>{item.title || item.kind}</strong>
                  <span>{item.feedback || '未发送'}</span>
                </div>
                <p>{item.message}</p>
                {canControl && (
                  <div className="today-candidate-actions">
                    <button
                      className="quiet-button icon-button"
                      type="button"
                      onClick={() => void sendFeedback(item.id, 'acknowledged')}
                      disabled={Boolean(busy)}
                      aria-label="认可这条候选"
                      title="认可这条候选"
                    >
                      {busy === `${item.id}:acknowledged` ? <LoaderCircle size={15} className="spin" /> : <Check size={15} />}
                    </button>
                    <button
                      className="quiet-button icon-button"
                      type="button"
                      onClick={() => void sendFeedback(item.id, 'too_frequent')}
                      disabled={Boolean(busy)}
                      aria-label="标记为太频繁"
                      title="标记为太频繁"
                    >
                      {busy === `${item.id}:too_frequent` ? <LoaderCircle size={15} className="spin" /> : <VolumeX size={15} />}
                    </button>
                  </div>
                )}
                <small>{formatCandidateTime(item.createdAt)}</small>
              </article>
            ))}
          </div>
        ) : (
          <div className="today-empty" role="status">暂无可展示的主动候选</div>
        )}
      </section>
      {notice && <p className="today-notice" role="status">{notice}</p>}
    </div>
  )
}

function formatCandidateTime(value: string): string {
  if (!value) return '等待新的线索'
  return value.replace('T', ' ').slice(5, 16)
}

function formatReportReason(reason: string): string {
  const labels: Record<string, string> = {
    insufficient_observation_days: '观察天数不足',
    daily_frequency_too_high: '日均频率偏高',
    insufficient_feedback: '反馈样本不足',
    recognition_rate_too_low: '认可率不足',
    too_frequent_feedback_present: '存在太频繁反馈',
  }
  return labels[reason] ?? reason
}

function formatGateReason(reason: string): string {
  const labels: Record<string, string> = {
    manual_review_not_ready: '人工复核未就绪',
    insufficient_long_term_observation: '长期观察不足',
    explicit_opt_in_required: '需要显式授权',
    shadow_only: '继续 Shadow',
  }
  return labels[reason] ?? reason
}

function formatGateTime(value: string | null): string {
  if (!value) return '等待首条候选'
  return value.replace('T', ' ').slice(0, 16)
}

function formatReviewAction(action: string): string {
  const labels: Record<string, string> = {
    keep_shadow: '继续 Shadow',
    manual_opt_in_available: '可人工授权',
  }
  return labels[action] ?? action
}
