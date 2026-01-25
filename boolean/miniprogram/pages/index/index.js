// index.ts
// 获取应用实例
const app = getApp()
// 引入API工具
const { worksApi } = require('../../utils/api')

Component({
  data: {
    featuredWorks: [],
    loading: true,
    error: ''
  },
  
  lifetimes: {
    attached() {
      // 页面加载时获取精选作品
      this.loadFeaturedWorks()
    }
  },
  
  methods: {
    // 加载精选作品
    async loadFeaturedWorks() {
      try {
        this.setData({ loading: true, error: '' })
        
        // 从API获取作品列表
        const result = await worksApi.getWorks()
        
        if (result.success) {
          // 获取前3个作品作为精选作品
          const featured = result.data.slice(0, 3).map(work => ({
            id: work.id,
            title: work.title,
            spaceType: this.getSpaceTypeText(work.type),
            area: work.area.toString(),
            coverImage: work.coverImage,
            location: work.location || ''
          }))
          
          this.setData({
            featuredWorks: featured,
            loading: false
          })
        } else {
          throw new Error(result.message || '获取作品失败')
        }
      } catch (error) {
        console.error('加载精选作品失败:', error)
        this.setData({
          error: '加载失败，请检查网络连接或稍后重试',
          loading: false
        })
      }
    },
    
    // 获取空间类型文本
    getSpaceTypeText(type) {
      const typeMap = {
        'residential': '家装设计',
        'office': '公装设计',
        'commercial': '商业空间',
        'other': '其他'
      }
      return typeMap[type] || type
    },
    
    // 手动重试加载
    onRetry() {
      this.loadFeaturedWorks()
    },
    
    // 预约咨询按钮点击事件
    onContact() {
      wx.navigateTo({
        url: '/pages/contact/contact'
      })
    }
  },
})
