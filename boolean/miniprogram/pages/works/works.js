// works.ts
const app = getApp()
// 引入API工具
const { worksApi } = require('../../utils/api')

Component({
  data: {
    currentType: 'all',
    hasMore: true,
    works: [],
    filteredWorks: [],
    loading: true,
    error: ''
  },
  
  lifetimes: {
    attached() {
      // 获取页面参数
      const pages = getCurrentPages()
      const currentPage = pages[pages.length - 1]
      const options = currentPage.options || {}
      
      if (options.type) {
        this.setData({
          currentType: options.type
        })
      }
      
      // 加载作品列表
      this.loadWorks()
    },
    
    show() {
      // 页面重新显示时刷新数据
      if (this.data.works.length > 0) {
        // 延迟刷新，避免频繁请求
        setTimeout(() => {
          this.loadWorks()
        }, 500)
      }
    }
  },
  
  methods: {
    // 加载作品列表
    async loadWorks() {
      try {
        this.setData({ loading: true, error: '' })
        
        // 从API获取作品列表
        const result = await worksApi.getWorks()
        
        if (result.success) {
          // 转换作品数据格式
          // 验证图片URL有效性
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
          
          const formattedWorks = result.data.map(work => ({
            id: work.id,
            title: work.title,
            spaceType: this.getSpaceTypeText(work.type),
            area: work.area.toString(),
            coverImage: validateImageUrl(work.coverImage) ? work.coverImage : '',
            type: work.type,
            views: work.views || 0,
            createdAt: work.createdAt || '',
            updatedAt: work.updatedAt || ''
          }))
          
          this.setData({
            works: formattedWorks,
            loading: false
          })
          
          // 应用筛选
          this.filterWorks()
        } else {
          throw new Error(result.message || '获取作品失败')
        }
      } catch (error) {
        console.error('加载作品列表失败:', error)
        this.setData({
          error: '加载失败，请检查网络连接或稍后重试',
          loading: false
        })
      }
    },
    
    // 手动重试加载
    onRetry() {
      this.loadWorks()
    },
    
    // 切换作品类型
    switchType(e) {
      const type = e.currentTarget.dataset.type
      this.setData({
        currentType: type
      })
      this.filterWorks()
    },
    
    // 筛选作品
    filterWorks() {
      const { currentType, works } = this.data
      let filtered
      
      if (currentType === 'all') {
        filtered = works
      } else {
        filtered = works.filter((work) => work.type === currentType)
      }
      
      this.setData({
        filteredWorks: filtered
      })
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
    
    // 下拉刷新
    onPullDownRefresh() {
      this.loadWorks()
      wx.stopPullDownRefresh()
    }
  }
})