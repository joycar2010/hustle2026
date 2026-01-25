// work-detail.ts
const app = getApp()
// 引入API工具
const { worksApi } = require('../../utils/api')

Component({
  data: {
    work: null,
    loading: true,
    error: ''
  },
  
  lifetimes: {
    attached() {
      // 获取页面参数
      const pages = getCurrentPages()
      const currentPage = pages[pages.length - 1]
      const options = currentPage.options || {}
      
      this.loadWorkDetailWithValidation(options.id)
    },
    
    show() {
      // 页面重新显示时刷新数据
      const pages = getCurrentPages()
      const currentPage = pages[pages.length - 1]
      const options = currentPage.options || {}
      
      this.loadWorkDetailWithValidation(options.id)
    }
  },
  
  methods: {
    // 验证ID并加载作品详情
    loadWorkDetailWithValidation(id) {
      // 验证ID是否有效
      if (!id || isNaN(Number(id))) {
        this.setData({
          loading: false,
          error: '无效的作品ID',
          work: null
        })
        return
      }
      
      // 转换为数字类型ID
      const numericId = Number(id)
      this.loadWorkDetail(numericId)
    },
    
    // 加载作品详情
    async loadWorkDetail(id) {
      try {
        this.setData({ loading: true, error: '', work: null })
        
        // 从API获取作品详情
        const result = await worksApi.getWorkDetail(id)
        
        if (result.success && result.data) {
          // 转换作品数据格式，处理可能的null或undefined值
          // 验证并过滤有效图片URL
          const validateImageUrl = (url) => {
            if (!url || typeof url !== 'string') return false;
            
            // 检查是否为Base64图片
            if (url.startsWith('data:image/')) {
              // 检查Base64图片格式是否正确
              return url.match(/^data:image\/(png|jpg|jpeg|gif|webp);base64,/) !== null;
            }
            
            // 检查是否为标准URL格式
            try {
              new URL(url);
              return true;
            } catch {
              // 检查是否为相对路径
              return url.startsWith('/') || url.startsWith('./') || url.startsWith('../');
            }
          };
          
          // 过滤有效图片
          const validImages = Array.isArray(result.data.images) 
            ? result.data.images.filter(img => validateImageUrl(img)) 
            : [];
          
          // 验证封面图片
          const validCoverImage = validateImageUrl(result.data.coverImage) ? result.data.coverImage : '';
          
          const work = {
            ...result.data,
            spaceType: this.getSpaceTypeText(result.data.type),
            area: result.data.area ? result.data.area.toString() : '',
            views: result.data.views || 0,
            location: result.data.location || '',
            title: result.data.title || '未知作品',
            description: result.data.description || '',
            coverImage: validCoverImage,
            images: validImages,
            createdAt: result.data.createdAt || '',
            updatedAt: result.data.updatedAt || ''
          }
          
          this.setData({
            work: work,
            loading: false,
            error: ''
          })
        } else {
          throw new Error(result.message || '获取作品详情失败')
        }
      } catch (error) {
        console.error('加载作品详情失败:', error)
        this.setData({ 
          error: error.message || '加载失败，请检查网络连接或稍后重试', 
          loading: false,
          work: null
        })
      }
    },
    
    // 手动重试加载
    onRetry() {
      // 获取页面参数
      const pages = getCurrentPages()
      const currentPage = pages[pages.length - 1]
      const options = currentPage.options || {}
      
      this.loadWorkDetailWithValidation(options.id)
    },
    
    // 获取空间类型文本
    getSpaceTypeText(type) {
      if (!type) return ''
      
      const typeMap = {
        'residential': '家装设计',
        'office': '公装设计',
        'commercial': '商业空间',
        'other': '其他'
      }
      return typeMap[type] || type
    },
    
    onContact() {
      wx.navigateTo({
        url: '/pages/contact/contact'
      })
    }
  }
})