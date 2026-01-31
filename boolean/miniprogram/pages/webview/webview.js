// pages/webview/webview.js
Page({
  /**
   * 页面的初始数据
   */
  data: {
    url: ''
  },

  /**
   * 生命周期函数--监听页面加载
   */
  onLoad(options) {
    if (options.url) {
      this.setData({
        url: decodeURIComponent(options.url)
      });
    }
  },

  /**
   * 生命周期函数--监听页面初次渲染完成
   */
  onReady() {

  },

  /**
   * 生命周期函数--监听页面显示
   */
  onShow() {

  },

  /**
   * 生命周期函数--监听页面隐藏
   */
  onHide() {

  },

  /**
   * 生命周期函数--监听页面卸载
   */
  onUnload() {
    // 页面卸载时清理webview相关资源
    this.setData({ url: '' });
  },

  /**
   * 页面相关事件处理函数--监听用户下拉动作
   */
  onPullDownRefresh() {
    wx.stopPullDownRefresh();
  },

  /**
   * 页面上拉触底事件的处理函数
   */
  onReachBottom() {

  },

  /**
   * 用户点击右上角分享
   */
  onShareAppMessage() {
    return {
      title: '布珥·迈拓空间设计',
      path: '/pages/webview/webview?url=' + encodeURIComponent(this.data.url)
    };
  },

  /**
   * 接收webview发送的消息
   */
  onMessage(e) {
    console.log('收到webview消息:', e);
  },

  /**
   * webview加载完成
   */
  onWebviewLoad(e) {
    console.log('webview加载完成:', e);
  },

  /**
   * webview加载失败
   */
  onError(e) {
    console.error('webview加载失败:', e);
    wx.showToast({
      title: '页面加载失败',
      icon: 'none'
    });
  }
});