import { useEffect, useState, useRef } from 'react'
import { useParams, useLocation, Link } from 'react-router-dom'
import { getCall, getAudioUrl, reprocessCall, CallDetail } from '../api'
import styles from './CallDetailPage.module.css'

const POLL_INTERVAL_MS = 5000
const IN_PROGRESS_STATUSES = new Set(['uploaded', 'converting', 'transcribing', 'analyzing'])

function fmtSeconds(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

function scoreColor(score: number): string {
  if (score === 1) return '#27ae60'
  if (score === 0.5) return '#e67e22'
  return '#e74c3c'
}

function scoreLabel(score: number): string {
  if (score === 1) return '✓'
  if (score === 0.5) return '~'
  return '✗'
}

export default function CallDetailPage() {
  const { id } = useParams<{ id: string }>()
  const callId = Number(id)
  const location = useLocation()
  const fromCallsList = (location.state as { from?: string } | null)?.from === 'calls'

  const [call, setCall] = useState<CallDetail | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reprocessing, setReprocessing] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  function seekTo(seconds: number) {
    if (audioRef.current) {
      audioRef.current.currentTime = seconds
      audioRef.current.play().catch(() => {})
    }
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  async function fetchCall() {
    const data = await getCall(callId)
    setCall(data)

    // Load audio URL once call reaches a terminal state
    if ((data.status === 'done' || data.status === 'error') && !audioUrl) {
      getAudioUrl(callId).then(r => setAudioUrl(r.url)).catch(() => {})
    }

    // Stop polling once processing is complete
    if (!IN_PROGRESS_STATUSES.has(data.status)) {
      stopPolling()
    }

    return data
  }

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchCall()
      .then((data) => {
        // Start polling if call is still in progress
        if (IN_PROGRESS_STATUSES.has(data.status)) {
          pollRef.current = setInterval(fetchCall, POLL_INTERVAL_MS)
        }
      })
      .catch(() => setError('Не удалось загрузить звонок'))
      .finally(() => setLoading(false))

    return () => stopPolling()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [callId])

  async function handleReprocess() {
    setReprocessing(true)
    try {
      await reprocessCall(callId)
      const updated = await fetchCall()
      // Start polling again since it's back in progress
      if (IN_PROGRESS_STATUSES.has(updated.status) && !pollRef.current) {
        pollRef.current = setInterval(fetchCall, POLL_INTERVAL_MS)
      }
    } catch {
      alert('Не удалось запустить повторную обработку. Попробуйте ещё раз.')
    } finally {
      setReprocessing(false)
    }
  }

  if (loading) return <div className={styles.state}>Загрузка…</div>
  if (error) return <div className={`${styles.state} ${styles.error}`}>{error}</div>
  if (!call) return <div className={styles.state}>Звонок не найден</div>

  const overallScore = call.analysis_results.length > 0
    ? call.analysis_results.reduce((sum, r) => sum + r.score, 0) / call.analysis_results.length
    : null

  return (
    <div>
      {fromCallsList ? (
        <Link to="/calls" className={styles.back}>← Назад к звонкам</Link>
      ) : (
        <Link to={`/projects/${call.project_id}`} className={styles.back}>← Назад к проекту</Link>
      )}

      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>{call.original_filename || `Звонок #${call.id}`}</h1>
          <div className={styles.meta}>
            {call.duration_seconds != null && (
              <span>{fmtSeconds(call.duration_seconds)}</span>
            )}
            {call.language && <span>Язык: {call.language}</span>}
            <span>{new Date(call.created_at).toLocaleString('ru-RU')}</span>
          </div>
          {call.comment && <p className={styles.comment}>💬 {call.comment}</p>}
        </div>

        {overallScore !== null && (
          <div className={styles.scoreCircle} style={{ background: scoreColor(overallScore) + '22' }}>
            <span className={styles.scoreNum} style={{ color: scoreColor(overallScore) }}>
              {(overallScore * 100).toFixed(0)}%
            </span>
            <span className={styles.scoreLabel}>общий балл</span>
          </div>
        )}
      </div>

      {call.status === 'error' && (
        <div className={styles.errorBox}>
          <strong>Ошибка обработки:</strong> {call.error_message || 'Неизвестная ошибка'}
          <button
            className={styles.reprocessBtn}
            onClick={handleReprocess}
            disabled={reprocessing}
          >
            {reprocessing ? 'Перезапуск…' : 'Повторить'}
          </button>
        </div>
      )}

      {call.group_analyses.length > 0 && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>Разбор AI</h2>
          <p className={styles.sectionDesc}>Отдельно по каждой группе метрик</p>
          {call.group_analyses.map(ga => (
            <div key={ga.metric_group_id} className={styles.aiGroup}>
              <div className={styles.aiGroupName}>{ga.metric_group_name}</div>
              {ga.summary && (
                <p className={styles.aiSummary}>{ga.summary}</p>
              )}
              {ga.pains_found.length > 0 && (
                <div className={styles.aiBlock}>
                  <div className={styles.aiBlockTitle}>Боли клиента в этом звонке</div>
                  <ul className={styles.aiList}>
                    {ga.pains_found.map((p, i) => <li key={i}>{p}</li>)}
                  </ul>
                </div>
              )}
              {ga.pains_addressed && (
                <div className={styles.aiBlock}>
                  <div className={styles.aiBlockTitle}>Как отработал</div>
                  <p className={styles.aiText}>{ga.pains_addressed}</p>
                </div>
              )}
              {ga.weak_spots.length > 0 && (
                <div className={styles.aiBlock}>
                  <div className={styles.aiBlockTitle}>Слабые места — что усилить</div>
                  <ul className={styles.aiListWeak}>
                    {ga.weak_spots.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {call.analysis_results.length > 0 && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>Оценка по критериям</h2>
          <div className={styles.resultsList}>
            {call.analysis_results.map(r => (
              <div key={r.metric_item_id} className={styles.resultRow}>
                <span
                  className={styles.scoreIcon}
                  style={{ background: scoreColor(r.score) + '22', color: scoreColor(r.score) }}
                >
                  {scoreLabel(r.score)}
                </span>
                <span className={styles.itemName}>{r.metric_item_name}</span>
                {r.timecode_start != null && (
                  audioUrl ? (
                    <button
                      type="button"
                      className={styles.timecodeBtn}
                      onClick={() => seekTo(r.timecode_start!)}
                    >
                      ▶ {fmtSeconds(r.timecode_start)}
                    </button>
                  ) : (
                    <span className={styles.timecode}>{fmtSeconds(r.timecode_start)}</span>
                  )
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {(audioUrl || call.transcription) && (
        <div className={styles.mediaSplit}>
          {audioUrl && (
            <div className={styles.section}>
              <div className={styles.audioHead}>
                <h2 className={styles.sectionTitle}>Запись</h2>
                <a href={audioUrl} target="_blank" rel="noopener noreferrer" className={styles.cloudLink}>
                  Открыть в облаке ↗
                </a>
              </div>
              <audio ref={audioRef} controls src={audioUrl} className={styles.audio} />
              <p className={styles.audioHint}>
                Ссылка на файл в облачном хранилище действует ограниченное время — открывайте со страницы звонка.
              </p>
            </div>
          )}

          {call.transcription && (
            <div className={styles.section}>
              <h2 className={styles.sectionTitle}>Транскрипция</h2>
              {call.transcription.segments.length > 0 ? (
                <div className={styles.transcriptSegments}>
                  {call.transcription.segments.map((seg, i) => (
                    <div
                      key={i}
                      className={audioUrl ? `${styles.segmentRow} ${styles.segmentRowClickable}` : styles.segmentRow}
                      onClick={audioUrl ? () => seekTo(seg.start) : undefined}
                    >
                      <span className={styles.segmentTime}>{fmtSeconds(seg.start)}</span>
                      <span className={styles.segmentText}>{seg.text}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <pre className={styles.transcript}>{call.transcription.full_text}</pre>
              )}
            </div>
          )}
        </div>
      )}

      {IN_PROGRESS_STATUSES.has(call.status) && (
        <div className={styles.processing}>
          ⏳ Звонок обрабатывается… (обновляется автоматически)
        </div>
      )}
    </div>
  )
}
