import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {beforeEach, expect, it} from 'vitest'
import {TodayPage} from './TodayPage'
import {ReviewInitiativeShadowPanel} from '../components/ReviewPanels'
import {ShadowCandidateCard} from '../components/ShadowCandidateCard'
import {loadAllInitiative, mergeInitiativeReview, resetInitiativeStore} from '../lib/initiativeStore'
import {initiativeReviewFixture} from '../lib/__tests__/initiativeFixture'
import {vi} from 'vitest'
import * as transport from '../adapters/localArcher'
vi.mock('../adapters/localArcher',()=>({getJson:vi.fn(),postJson:vi.fn()}))
const item={id:8,kind:'thread_resume',eventType:'initiative_due',title:'合成候选',message:'仅用于检查',decisionTrace:{threadId:42},delivered:false,createdAt:'',feedback:'',archivedAt:null}
beforeEach(()=>{resetInitiativeStore();vi.resetAllMocks()})
it('initial loading is distinct from an empty successful report',()=>{
const html=renderToStaticMarkup(<TodayPage canControl onRefresh={async()=>{}} onNavigate={()=>{}}/>);
expect(html).toContain('正在读取观察数据');expect(html).not.toContain('暂无可展示')
})
it('a failed report retains content and disables every mutation in both pages',async()=>{
mergeInitiativeReview({...initiativeReviewFixture,items:[item]});vi.mocked(transport.getJson).mockRejectedValue(new Error('合成报告失败'));await loadAllInitiative();
const today=renderToStaticMarkup(<TodayPage canControl onRefresh={async()=>{}} onNavigate={()=>{}}/>);
expect(today).toContain('合成候选');expect(today).toContain('role="alert"');expect(today.match(/disabled=""/g)).toHaveLength(8);
const review=renderToStaticMarkup(<ReviewInitiativeShadowPanel canControl/>);
expect(review).toContain('合成报告失败');expect(review).toContain('合成候选');expect(review).toContain('刷新观察数据');expect(review.match(/disabled=""/g)).toHaveLength(1)
})
it('workspace feedback and lifecycle controls obey the same read-only boundary',()=>{
const html=renderToStaticMarkup(<ShadowCandidateCard item={item} busy="" notice="" onAcknowledge={()=>{}} onTooFrequent={()=>{}} onMute={()=>{}} onViewAll={()=>{}} canControl={false}/>);
expect(html.match(/disabled=""/g)).toHaveLength(7)
})
