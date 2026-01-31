// app.js
App({
  globalData: {},
  onLaunch() {
    // 展示本地存储能力
    const logs = wx.getStorageSync('logs') || []
    logs.unshift(Date.now())
    wx.setStorageSync('logs', logs)

    // 初始化云函数
    try {
      wx.cloud.init({
        env: 'your-cloud-env-id', // 请替换为你的云函数环境ID
        traceUser: true
      })
      console.log('云函数初始化成功')
    } catch (error) {
      console.warn('云函数初始化失败，在本地开发环境中可能需要部署云函数', error)
    }

    // 登录
    wx.login({
      success: res => {
        console.log(res.code)
        // 发送 res.code 到后台换取 openId, sessionKey, unionId
      },
    })
  },
})