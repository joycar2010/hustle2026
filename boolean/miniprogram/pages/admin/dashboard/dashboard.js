// dashboard.js
const app = getApp()

Component({
  data: {
    // 管理后台数据
  },
  
  lifetimes: {
    attached() {
      // 页面加载时的初始化逻辑
    }
  },
  
  methods: {
    // 添加新作品
    addWork() {
      wx.showToast({
        title: '添加作品功能开发中',
        icon: 'none'
      })
    },
    
    // 查看新线索
    viewLeads() {
      wx.showToast({
        title: '线索管理功能开发中',
        icon: 'none'
      })
    }
  }
})