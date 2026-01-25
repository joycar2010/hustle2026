// login.ts
const app = getApp()

Component({
  data: {
    // 登录页面数据
  },
  
  lifetimes: {
    attached() {
      // 页面加载时的初始化逻辑
    }
  },
  
  methods: {
    // 登录处理
    login(e) {
      const { username, password } = e.detail.value
      
      // 简单的模拟登录验证
      if (username === 'admin' && password === 'admin123') {
        wx.showToast({
          title: '登录成功',
          icon: 'success',
          success: () => {
            // 登录成功后跳转到管理后台
            wx.navigateTo({
              url: '/pages/admin/dashboard/dashboard'
            })
          }
        })
      } else {
        wx.showToast({
          title: '账号或密码错误',
          icon: 'none'
        })
      }
    }
  }
})