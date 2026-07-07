<template>
  <div>
    <el-card body-style="padding:16px">
      <template #header>
        <span class="ch"><el-icon><Link/></el-icon> 官网管理 · 站点内容配置</span>
        <span style="float:right;font-size:12px;color:#909399">改后热生效 · 与交易引擎完全隔离</span>
      </template>

      <el-tabs v-model="site" @tab-change="onTab">
        <el-tab-pane label="qh 交易端 (顶栏品牌)" name="qh"/>
        <el-tab-pane label="qhwww 介绍站 (全量)" name="qhwww"/>
        <el-tab-pane label="qhadmin 运营后台 (侧栏品牌)" name="qhadmin"/>
      </el-tabs>

      <!-- ============ qh 顶栏品牌(直存热生效) ============ -->
      <el-form v-if="site==='qh'" label-width="130px" style="max-width:640px" v-loading="loading">
        <el-divider content-position="left">顶栏品牌 (qh.hustle2026.xyz 左上角)</el-divider>
        <el-form-item label="平台名称"><el-input v-model="qh.brand.platformName" placeholder="Quant Hedge" clearable/></el-form-item>
        <el-form-item label="顶栏标题"><el-input v-model="qh.brand.title" placeholder="【Quant Hedge】对冲工具软件" clearable/>
          <div class="hint">qh 左上角标题(也用作浏览器标签标题)</div></el-form-item>
        <el-form-item label="LOGO 地址"><el-input v-model="qh.brand.logo" placeholder="QHEDGELOGO-s-single.ico 或 https://... " clearable/></el-form-item>
        <el-divider content-position="left">官网按钮</el-divider>
        <el-form-item label="官网跳转地址"><el-input v-model="qh.officialUrl" placeholder="https://app.hustle2026.xyz" clearable/></el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveQh"><el-icon style="margin-right:4px"><Check/></el-icon>保存并热生效</el-button>
          <el-button @click="loadQh">重新加载</el-button>
          <el-button link type="primary" @click="open('https://qh.hustle2026.xyz/')">预览 qh →</el-button>
        </el-form-item>
      </el-form>

      <!-- ============ qhadmin 运营后台侧栏品牌(直存热生效, 消费端 Layout.vue) ============ -->
      <el-form v-else-if="site==='qhadmin'" label-width="130px" style="max-width:640px" v-loading="loading">
        <el-divider content-position="left">侧栏品牌 (qhadmin.hustle2026.xyz 左侧菜单顶部)</el-divider>
        <el-form-item label="侧栏 LOGO">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <div style="width:150px;height:44px;background:#08113A;border-radius:6px;display:flex;align-items:center;justify-content:center;cursor:pointer;overflow:hidden"
                 @click="pickAdminLogo" title="点击上传 LOGO 图片(<200KB, 转 base64 存配置; 深底预览=侧栏实际底色)">
              <img v-if="qha.brand.logo" :src="qha.brand.logo" style="max-height:26px;max-width:140px;object-fit:contain"/>
              <span v-else style="color:#9fb0d6;font-size:12px">+ 点击上传</span>
            </div>
            <el-button v-if="qha.brand.logo" link type="danger" size="small" @click="qha.brand.logo=''">清除</el-button>
          </div>
          <el-input v-model="qha.brand.logo" placeholder="/logo-white.png 或 https://... (也可点上方深底框上传)" clearable style="margin-top:6px"/>
          <div class="hint">支持 URL 或上传图片(存配置, &lt;200KB); 侧栏为深蓝底, 建议透明底浅色图。留空=默认 /logo-white.png</div>
        </el-form-item>
        <el-form-item label="侧栏标题"><el-input v-model="qha.brand.title" placeholder="Quant Hedge" clearable/>
          <div class="hint">LOGO 右侧标题文字(侧栏收起时自动隐藏)</div></el-form-item>
        <el-form-item label="登录页标题"><el-input v-model="qha.brand.loginTitle" placeholder="QUANT HEDGE" clearable/>
          <div class="hint">未登录蒙层登录卡片上的大标题(留空=跟随侧栏标题)</div></el-form-item>
        <el-form-item label="浏览器标签标题"><el-input v-model="qha.brand.docTitle" placeholder="QH 运营后台" clearable/></el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveQha"><el-icon style="margin-right:4px"><Check/></el-icon>保存并热生效</el-button>
          <el-button @click="loadQha">重新加载</el-button>
        </el-form-item>
        <div class="hint">保存后本后台侧栏/登录页/标签标题即时生效(其他已打开的浏览器页刷新生效)。</div>
      </el-form>

      <!-- ============ qhwww 介绍站(草稿/发布/回滚) ============ -->
      <div v-else v-loading="loading">
        <el-alert :type="hasDraft?'warning':'success'" :closable="false" show-icon style="margin-bottom:12px"
          :title="hasDraft?'有未发布草稿 — 编辑保存进草稿, 点「发布上线」才对外生效':'当前与线上一致 — 编辑后可先存草稿, 确认再发布'">
          <div style="margin-top:6px">
            <el-button type="primary" size="small" :loading="saving" @click="saveDraft">保存草稿</el-button>
            <el-button type="danger" size="small" :loading="publishing" @click="publish"><el-icon style="margin-right:3px"><Upload/></el-icon>发布上线</el-button>
            <el-button size="small" @click="loadWww">放弃改动/重载</el-button>
            <el-button link type="primary" size="small" @click="open('https://qhwww.hustle2026.xyz/')">预览 qhwww →</el-button>
            <el-select v-model="rbVer" size="small" placeholder="选版本回滚" style="width:200px;margin-left:10px" @change="doRollback">
              <el-option v-for="v in versions" :key="v.id" :label="'#'+v.id+' · '+fmt(v.ts)" :value="v.id"/>
            </el-select>
          </div>
        </el-alert>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-divider content-position="left">品牌</el-divider>
            <el-form label-width="90px">
              <el-form-item label="平台名称"><el-input v-model="www.brand.platformName" placeholder="Quant Hedge"/></el-form-item>
              <el-form-item label="LOGO"><el-input v-model="www.brand.logo" placeholder="/QHEDGELOGO-mid-single.png 或 URL"/></el-form-item>
            </el-form>

            <el-divider content-position="left">首屏文案 (Hero)</el-divider>
            <el-form label-width="90px">
              <el-form-item label="主标题"><el-input v-model="www.hero.title" placeholder="把专业对冲量化"/></el-form-item>
              <el-form-item label="副标题"><el-input v-model="www.hero.subtitle" placeholder="一套系统，覆盖对冲套利全流程"/></el-form-item>
              <el-form-item label="标语"><el-input v-model="www.hero.tagline" placeholder="(可选)"/></el-form-item>
            </el-form>

            <el-divider content-position="left">区块标题 (文字)</el-divider>
            <el-form label-width="90px">
              <el-form-item v-for="k in secKeys" :key="k" :label="k">
                <el-input v-model="www.sections[k]" size="small"/>
              </el-form-item>
            </el-form>
          </el-col>

          <el-col :span="12">
            <el-divider content-position="left">导航菜单 <el-button link type="primary" size="small" @click="www.nav.push({name:'',anchor:'#'})">+ 增加</el-button></el-divider>
            <div v-for="(it,i) in www.nav" :key="'n'+i" class="row2">
              <el-input v-model="it.name" size="small" placeholder="菜单名" style="width:130px"/>
              <el-input v-model="it.anchor" size="small" placeholder="#锚点 或 URL" style="width:150px"/>
              <el-button link type="danger" size="small" @click="www.nav.splice(i,1)">删</el-button>
            </div>

            <el-divider content-position="left">按钮跳转 <el-button link type="primary" size="small" @click="www.buttons.push({key:'',label:'',url:''})">+ 增加</el-button></el-divider>
            <div v-for="(b,i) in www.buttons" :key="'b'+i" class="row2">
              <el-input v-model="b.key" size="small" placeholder="key(标识)" style="width:90px" title="按钮标识(P2 绑定用, 如 download/login/learn)"/>
              <el-input v-model="b.label" size="small" placeholder="按钮文字" style="width:130px"/>
              <el-input v-model="b.url" size="small" placeholder="跳转URL" style="width:170px"/>
              <el-button link type="danger" size="small" @click="www.buttons.splice(i,1)">删</el-button>
            </div>

            <el-divider content-position="left">客户端下载 <el-button link type="primary" size="small" @click="www.downloads.push({os:'',label:'',url:'',ver:''})">+ 增加</el-button></el-divider>
            <div v-for="(d,i) in www.downloads" :key="'d'+i" class="row2">
              <el-input v-model="d.os" size="small" placeholder="系统" style="width:80px"/>
              <el-input v-model="d.label" size="small" placeholder="安装包名" style="width:150px"/>
              <el-input v-model="d.url" size="small" placeholder="下载URL" style="width:150px"/>
              <el-input v-model="d.ver" size="small" placeholder="版本" style="width:70px"/>
              <el-button link type="danger" size="small" @click="www.downloads.splice(i,1)">删</el-button>
            </div>
          </el-col>
        </el-row>

        <el-divider content-position="left">底部 · 联系与备案</el-divider>
        <el-row :gutter="12">
          <el-col :span="8"><el-form label-width="76px">
            <el-form-item label="客服邮箱"><el-input v-model="www.footer.email" size="small"/></el-form-item>
            <el-form-item label="客服QQ"><el-input v-model="www.footer.qq" size="small"/></el-form-item>
            <el-form-item label="联系电话"><el-input v-model="www.footer.phone" size="small"/></el-form-item>
          </el-form></el-col>
          <el-col :span="8"><el-form label-width="76px">
            <el-form-item label="ICP备案"><el-input v-model="www.footer.icp" size="small" placeholder="浙ICP备…号"/></el-form-item>
            <el-form-item label="备案链接"><el-input v-model="www.footer.icpUrl" size="small" placeholder="https://beian.miit.gov.cn"/></el-form-item>
            <el-form-item label="公网安备"><el-input v-model="www.footer.police" size="small"/></el-form-item>
          </el-form></el-col>
          <el-col :span="8"><el-form label-width="76px">
            <el-form-item label="版权文字"><el-input v-model="www.footer.copyright" size="small"/></el-form-item>
            <el-form-item label="协议标题"><el-input v-model="www.footer.agreementTitle" size="small"/></el-form-item>
          </el-form></el-col>
        </el-row>
        <el-form-item label="服务协议正文" label-width="90px">
          <el-input v-model="www.footer.agreementHtml" type="textarea" :rows="4" placeholder="支持 HTML(留空=用介绍站内置协议)"/>
          <div class="hint">留空则用 qhwww 内置协议; 填写则覆盖(支持 HTML 富文本)</div>
        </el-form-item>

        <el-divider content-position="left">底部 · 二维码 (点击上传, 图片存配置, &lt;400KB)</el-divider>
        <div style="display:flex;gap:20px;flex-wrap:wrap">
          <div v-for="q in qrDefs" :key="q.k" style="text-align:center">
            <div style="width:110px;height:110px;border:1px dashed #c3cbd2;border-radius:8px;display:flex;align-items:center;justify-content:center;cursor:pointer;background:#fafbfc;overflow:hidden"
                 @click="pickQR(q.k)" :title="'点击上传'+q.n">
              <img v-if="www.footer.qrs[q.k]" :src="www.footer.qrs[q.k]" style="width:100%;height:100%;object-fit:contain"/>
              <span v-else style="color:#909399;font-size:12px">+ 上传</span>
            </div>
            <div style="font-size:12px;margin-top:4px">{{q.n}}
              <el-button v-if="www.footer.qrs[q.k]" link type="danger" size="small" @click="www.footer.qrs[q.k]=''">清除</el-button>
            </div>
          </div>
        </div>
        <div class="hint" style="margin-top:12px">全部改动先「保存草稿」不对外, 确认后「发布上线」→ qhwww 加载即读本配置渲染(品牌/导航/文案/按钮/下载/底部/二维码/协议)。</div>
      </div>
    </el-card>
  </div>
</template>
<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
const site=ref('qh'), loading=ref(false), saving=ref(false), publishing=ref(false)
const hasDraft=ref(false), versions=ref([]), rbVer=ref(null)
const secKeys=['features','devices','ai','member','rewards','plans']
const qh=reactive({ brand:{platformName:'',title:'',logo:''}, officialUrl:'' })
const qha=reactive({ brand:{title:'',logo:'',loginTitle:'',docTitle:''} })
const www=reactive({ brand:{platformName:'',logo:''}, hero:{title:'',subtitle:'',tagline:''},
  sections:{}, nav:[], buttons:[], downloads:[],
  footer:{ email:'',qq:'',phone:'',copyright:'',icp:'',icpUrl:'',police:'',agreementTitle:'',agreementHtml:'',
           qrs:{wechatOA:'',wechatMini:'',douyin:'',kuaishou:''} } })
const qrDefs=[{k:'wechatOA',n:'微信公众号'},{k:'wechatMini',n:'微信小程序'},{k:'douyin',n:'抖音号'},{k:'kuaishou',n:'快手号'}]
function pickQR(key){
  const inp=document.createElement('input'); inp.type='file'; inp.accept='image/*'
  inp.onchange=function(){ const f=inp.files&&inp.files[0]; if(!f)return
    if(f.size>400*1024){ ElMessage.warning('二维码图片请 <400KB'); return }
    const rd=new FileReader(); rd.onload=function(){ www.footer.qrs[key]=rd.result }; rd.readAsDataURL(f) }
  inp.click()
}
function fmt(t){ return (t||'').replace('T',' ').slice(0,19) }
function open(u){ window.open(u,'_blank') }
function onTab(){ site.value==='qh'?loadQh():(site.value==='qhadmin'?loadQha():loadWww()) }
// ---- qhadmin 侧栏品牌 ----
function pickAdminLogo(){
  const inp=document.createElement('input'); inp.type='file'; inp.accept='image/*'
  inp.onchange=function(){ const f=inp.files&&inp.files[0]; if(!f)return
    if(f.size>200*1024){ ElMessage.warning('LOGO 图片请 <200KB(存配置内, 过大拖慢后台加载)'); return }
    const rd=new FileReader(); rd.onload=function(){ qha.brand.logo=rd.result }; rd.readAsDataURL(f) }
  inp.click()
}
async function loadQha(){ loading.value=true
  try{ const r=await api.siteGet('qhadmin'); const b=((r&&r.cfg)||{}).brand||{}
    qha.brand.title=b.title||''; qha.brand.logo=b.logo||''; qha.brand.loginTitle=b.loginTitle||''; qha.brand.docTitle=b.docTitle||'' }
  catch(e){ ElMessage.error('加载失败') } finally{ loading.value=false } }
async function saveQha(){ saving.value=true
  try{ const cfg={ brand:{title:qha.brand.title.trim(),logo:(qha.brand.logo||'').trim(),
      loginTitle:qha.brand.loginTitle.trim(),docTitle:qha.brand.docTitle.trim()} }
    await api.siteSave('qhadmin',cfg)
    // 本页所在的 qhadmin 即时热生效(Layout 监听); 其他已开页面刷新生效
    window.dispatchEvent(new CustomEvent('qha-brand-updated',{detail:cfg.brand}))
    ElMessage.success('已保存 · 本后台侧栏即时生效') }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败(需超管权限)') } finally{ saving.value=false } }
// ---- qh ----
async function loadQh(){ loading.value=true
  try{ const r=await api.siteGet('qh'); const c=(r&&r.cfg)||{}; const b=c.brand||{}
    qh.brand.platformName=b.platformName||''; qh.brand.title=b.title||''; qh.brand.logo=b.logo||''; qh.officialUrl=c.officialUrl||'' }
  catch(e){ ElMessage.error('加载失败') } finally{ loading.value=false } }
async function saveQh(){ saving.value=true
  try{ await api.siteSave('qh',{ brand:{platformName:qh.brand.platformName.trim(),title:qh.brand.title.trim(),logo:qh.brand.logo.trim()}, officialUrl:qh.officialUrl.trim() })
    ElMessage.success('已保存 · qh 顶栏刷新即生效') }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败(需超管权限)') } finally{ saving.value=false } }
// ---- qhwww ----
function fillWww(c){ c=c||{}
  Object.assign(www.brand,{platformName:'',logo:''},c.brand||{})
  Object.assign(www.hero,{title:'',subtitle:'',tagline:''},c.hero||{})
  www.sections={}; secKeys.forEach(k=>www.sections[k]=(c.sections&&c.sections[k])||'')
  www.nav=Array.isArray(c.nav)?JSON.parse(JSON.stringify(c.nav)):[]
  www.buttons=Array.isArray(c.buttons)?JSON.parse(JSON.stringify(c.buttons)):[]
  www.downloads=Array.isArray(c.downloads)?JSON.parse(JSON.stringify(c.downloads)):[]
  const ft=c.footer||{}; Object.assign(www.footer,{email:'',qq:'',phone:'',copyright:'',icp:'',icpUrl:'',police:'',agreementTitle:'',agreementHtml:''},
    {email:ft.email,qq:ft.qq,phone:ft.phone,copyright:ft.copyright,icp:ft.icp,icpUrl:ft.icpUrl,police:ft.police,agreementTitle:ft.agreementTitle,agreementHtml:ft.agreementHtml})
  www.footer.qrs={wechatOA:'',wechatMini:'',douyin:'',kuaishou:''}; Object.assign(www.footer.qrs, ft.qrs||{}) }
async function loadWww(){ loading.value=true; rbVer.value=null
  try{ const r=await api.siteDraftGet('qhwww'); hasDraft.value=!!r.has_draft
    fillWww(r.has_draft?r.draft:r.live)
    try{ const v=await api.siteVersions('qhwww'); versions.value=v.versions||[] }catch(e){}
  }catch(e){ ElMessage.error('加载失败') } finally{ loading.value=false } }
function collect(){ return { brand:{...www.brand}, hero:{...www.hero}, sections:{...www.sections},
  nav:www.nav.filter(x=>x.name), buttons:www.buttons.filter(x=>x.label), downloads:www.downloads.filter(x=>x.os||x.label),
  footer:{...www.footer, qrs:{...www.footer.qrs}} } }
async function saveDraft(){ saving.value=true
  try{ await api.siteDraftSave('qhwww',collect()); hasDraft.value=true; ElMessage.success('草稿已保存(未对外发布)') }
  catch(e){ ElMessage.error(e?.response?.data?.detail||'保存失败') } finally{ saving.value=false } }
async function publish(){
  try{ await ElMessageBox.confirm('将当前内容发布到 qhwww 线上(自动存历史可回滚), 确认?','发布上线',{type:'warning'})
    publishing.value=true; await api.sitePublish('qhwww',collect()); hasDraft.value=false
    ElMessage.success('已发布上线'); try{ const v=await api.siteVersions('qhwww'); versions.value=v.versions||[] }catch(e){}
  }catch(e){ if(e!=='cancel')ElMessage.error(e?.response?.data?.detail||'发布失败') } finally{ publishing.value=false } }
async function doRollback(id){ if(!id)return
  try{ await ElMessageBox.confirm('回滚到版本 #'+id+'? 当前内容会先存历史。','版本回滚',{type:'warning'})
    await api.siteRollback('qhwww',id); ElMessage.success('已回滚 #'+id); rbVer.value=null; loadWww() }
  catch(e){ rbVer.value=null; if(e!=='cancel')ElMessage.error('回滚失败') } }
onMounted(loadQh)
</script>
<style scoped>
.ch{font-weight:600;display:inline-flex;align-items:center;gap:6px}
.hint{font-size:11.5px;color:#909399;line-height:1.5;margin-top:2px}
.row2{display:flex;align-items:center;gap:6px;margin-bottom:6px}
</style>
