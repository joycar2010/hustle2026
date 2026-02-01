// pages/works/works.js
const api = require('../../utils/api');

Page({
  /**
   * 页面的初始数据
   */
  data: {
    worksList: [],
    categories: [],
    filterType: '',
    total: 0,
    page: 1,
    pageSize: 12,
    hasMore: true,
    loading: false,
    categoriesLoading: false,
    userPermissions: {
      viewWorks: false,
      categories: []
    }
  },

  /**
   * 生命周期函数--监听页面加载
   */
  onLoad(options) {
    // 从url参数获取筛选类型
    if (options.type) {
      this.setData({
        filterType: options.type
      });
    }
    // 获取用户权限
    this.getUserPermissions();
    // 获取分类数据
    this.getCategories();
  },

  /**
   * 获取分类数据
   */
  getCategories() {
    this.setData({ categoriesLoading: true });
    
    api.categoryApi.getCategories().then(res => {
      // 处理分类数据
      const categories = res.data || [];
      this.setData({
        categories: categories,
        categoriesLoading: false
      });
    }).catch(err => {
      console.error('加载分类失败:', err);
      this.setData({ categoriesLoading: false });
    });
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
    // 每次页面显示时重新获取用户权限并加载数据
    this.getUserPermissions();
    // 每次页面显示时重新获取分类数据，确保数据同步更新
    this.getCategories();
  },
  
  /**
   * 获取用户权限
   */
  getUserPermissions() {
    // 获取全局应用实例
    const appInstance = getApp();
    
    // 使用全局用户权限
    this.setData({
      userPermissions: appInstance.globalData.userPermissions
    });
    
    // 加载作品列表
    this.loadWorks();
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

  },

  /**
   * 页面相关事件处理函数--监听用户下拉动作
   */
  onPullDownRefresh() {
    this.setData({
      page: 1,
      worksList: []
    });
    this.loadWorks();
    wx.stopPullDownRefresh();
  },

  /**
   * 页面上拉触底事件的处理函数
   */
  onReachBottom() {
    if (this.data.worksList.length < this.data.total) {
      this.loadMore();
    }
  },

  /**
   * 用户点击右上角分享
   */
  onShareAppMessage() {
    return {
      title: '布珥·迈拓空间设计 - 设计作品',
      path: '/pages/works/works'
    };
  },

  /**
   * 验证图片URL是否有效
   * @param {string} url - 图片URL
   * @returns {boolean} - 是否有效
   */
  validateImageUrl(url) {
    if (!url || typeof url !== 'string') {
      return false;
    }
    
    // 检查是否是Base64编码的图片
    if (url.startsWith('data:image/')) {
      return true;
    }
    
    // 检查是否是placeholder域名（过滤掉占位符图片）
    if (url.includes('via.placeholder.com')) {
      return false;
    }
    
    // 检查是否是有效的HTTP/HTTPS URL
    const httpRegex = /^(https?:\/\/)[\w.-]+(?:\.[\w\.-]+)+[\w\-\._~:/?#[\]@!\$&'\(\)\*\+,;=.]+$/;
    if (!httpRegex.test(url)) {
      return false;
    }
    
    // 检查域名是否有效（简单检查，避免明显无效的域名）
    const domainRegex = /^(https?:\/\/)([a-zA-Z0-9][a-zA-Z0-9-]{1,61}[a-zA-Z0-9]\.)+[a-zA-Z]{2,}$/;
    return domainRegex.test(url);
  },

  /**
   * 处理富文本数据，将相对路径图片转换为完整URL
   * @param {string} html - 富文本HTML
   * @returns {string} - 处理后的富文本HTML
   */
  processRichText(html) {
    if (!html || typeof html !== 'string') {
      return html;
    }
    
    // 处理图片路径，将相对路径转换为完整URL
    const baseUrl = 'http://localhost:3001';
    let processedHtml = html;
    
    // 替换相对路径的图片
    processedHtml = processedHtml.replace(/<img\s+src="\/([^"]+)"[^>]*>/gi, (match, src) => {
      return `<img src="${baseUrl}/${src}" alt="作品图片" style="max-width: 100%; height: auto;"/>`;
    });
    
    // 限制富文本内容长度，只显示前100个字符的纯文本
    const plainText = processedHtml.replace(/<[^>]*>/g, '').substring(0, 100);
    return plainText;
  },

  /**
   * 加载作品列表
   */
  loadWorks() {
    this.setData({ loading: true });

    const params = {
      page: this.data.page,
      pageSize: this.data.pageSize
    };

    if (this.data.filterType) {
      params.type = this.data.filterType;
    }

    api.worksApi.getWorks(params).then(res => {
      const { userPermissions } = this.data;
      
      // 处理作品数据，验证图片URL并根据权限过滤
      const processedWorks = (res.data || []).filter(work => {
        // 检查作品是否公开
        if (work.isPublic === true) {
          return true;
        }
        
        // 非公开作品需要检查用户权限
        // 检查用户是否有查看作品的基本权限
        if (!userPermissions.viewWorks) {
          return false;
        }
        
        // 检查分类权限
        if (work.type && userPermissions.categories && userPermissions.categories.length > 0) {
          if (!userPermissions.categories.includes(work.type)) {
            return false;
          }
        }
        
        return true;
      }).map(work => {
        // 处理图片数据
        if (work.images && Array.isArray(work.images)) {
          work.images = work.images.filter(imageUrl => this.validateImageUrl(imageUrl));
        } else {
          work.images = [];
        }
        
        // 处理富文本描述
        if (work.description) {
          work.processedDescription = this.processRichText(work.description);
        } else {
          work.processedDescription = '融合现代美学与实用功能的空间设计';
        }
        
        return work;
      });
      
      // 检查是否有作品可显示
      if (processedWorks.length === 0) {
        // 显示无作品提示
        wx.showToast({
          title: '暂无作品',
          icon: 'none',
          duration: 3000
        });
      }
      
      this.setData({
        worksList: this.data.page === 1 ? processedWorks : [...this.data.worksList, ...processedWorks],
        total: res.total || 0,
        hasMore: (this.data.page === 1 ? processedWorks.length : this.data.worksList.length + processedWorks.length) < (res.total || 0),
        loading: false
      });
    }).catch(err => {
      console.error('加载作品失败:', err);
      this.setData({ loading: false });
      wx.showToast({
        title: '加载失败，请重试',
        icon: 'none'
      });
    });
  },

  /**
   * 加载更多作品
   */
  loadMore() {
    this.setData({
      page: this.data.page + 1
    });
    this.loadWorks();
  },

  /**
   * 设置筛选类型
   */
  setFilterType(e) {
    const type = e.currentTarget.dataset.type;
    this.setData({
      filterType: type,
      page: 1,
      worksList: []
    });
    this.loadWorks();
  },

  /**
   * 跳转到作品详情页
   */
  navigateToWorkDetail(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({
      url: `/pages/work-detail/work-detail?id=${id}`
    });
  }
});
