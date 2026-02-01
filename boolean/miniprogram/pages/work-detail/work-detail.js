// pages/work-detail/work-detail.js
const api = require('../../utils/api');

Page({
  /**
   * 页面的初始数据
   */
  data: {
    work: {
      id: '',
      title: '',
      images: [],
      spaceType: '',
      area: '',
      location: '',
      description: '',
      features: []
    },
    relatedProjects: [],
    userInfo: null,
    userPermissions: {
      viewWorks: false,
      categories: []
    },
    isLoading: true,
    unauthorized: false,
    unauthorizedReason: ''
  },

  /**
   * 生命周期函数--监听页面加载
   */
  onLoad(options) {
    const id = options.id;
    if (id) {
      // 获取全局应用实例
      const appInstance = getApp();
      
      // 使用全局用户信息和权限
      this.setData({
        userInfo: appInstance.globalData.userInfo,
        userPermissions: appInstance.globalData.userPermissions
      });
      
      // 加载作品详情
      this.loadWorkDetail(id);
    } else {
      wx.showToast({
        title: '参数错误',
        icon: 'none'
      });
      setTimeout(() => {
        wx.navigateBack();
      }, 1500);
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
    // 每次页面显示时更新用户权限，确保权限变更实时生效
    if (this.data.work.id) {
      const appInstance = getApp();
      
      // 更新用户信息和权限
      this.setData({
        userInfo: appInstance.globalData.userInfo,
        userPermissions: appInstance.globalData.userPermissions
      });
      
      // 权限更新后重新加载数据
      this.loadWorkDetail(this.data.work.id);
    }
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
    const pages = getCurrentPages();
    const currentPage = pages[pages.length - 1];
    const id = currentPage.options.id;
    this.loadWorkDetail(id);
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
      title: `布珥·迈拓空间设计 - ${this.data.work.title}`,
      path: `/pages/work-detail/work-detail?id=${this.data.work.id}`
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
   * 加载作品详情
   */
  loadWorkDetail(id) {
    wx.showLoading({
      title: '加载中...'
    });

    const appInstance = getApp();
    const isCustomerInDatabase = appInstance.globalData.isAuthenticated;
    
    // 获取用户OpenID
    let openId = '';
    try {
      // 从本地存储获取OpenID
      openId = wx.getStorageSync('openId') || '';
    } catch (e) {
      console.error('获取OpenID失败:', e);
    }

    api.worksApi.getWorkDetail(id, openId).then(res => {
      let workData = res.data || this.data.work;
      
      // 处理富文本数据，将相对路径图片转换为完整URL
      if (workData.description) {
        workData.description = this.processRichText(workData.description);
      }
      if (workData.designDescription) {
        workData.designDescription = this.processRichText(workData.designDescription);
      }
      if (workData.designConcept) {
        workData.designConcept = this.processRichText(workData.designConcept);
      }
      if (workData.functionPlanning) {
        workData.functionPlanning = this.processRichText(workData.functionPlanning);
      }
      if (workData.materialSelection) {
        workData.materialSelection = this.processRichText(workData.materialSelection);
      }
      
      // 处理图片数据，验证图片URL
      if (workData.images && Array.isArray(workData.images)) {
        workData.images = workData.images.filter(imageUrl => this.validateImageUrl(imageUrl));
      } else {
        workData.images = [];
      }
      
      // 客户身份验证和访问权限控制
      // 首先检查作品是否公开，对于未设置isPublic字段的作品，默认视为不公开
      if (workData.isPublic !== true) {
        // 作品不公开，需要检查用户权限
        if (!isCustomerInDatabase) {
          // 客户不在数据库中，限制访问
          wx.hideLoading();
          this.setData({
            isLoading: false,
            unauthorized: true,
            unauthorizedReason: '该作品未开放，仅对注册客户可见'
          });
          return;
        } else {
          // 客户已在数据库中，检查具体权限
          const { userPermissions } = this.data;
          
          // 检查用户是否有查看权限
          if (!userPermissions.viewWorks) {
            // 用户没有查看作品的权限
            wx.hideLoading();
            this.setData({
              isLoading: false,
              unauthorized: true,
              unauthorizedReason: '您没有查看作品的权限'
            });
            return;
          }
          
          // 检查按分类的权限
          if (workData.type && userPermissions.categories && userPermissions.categories.length > 0) {
            if (!userPermissions.categories.includes(workData.type)) {
              // 用户没有查看该分类作品的权限
              wx.hideLoading();
              this.setData({
                isLoading: false,
                unauthorized: true,
                unauthorizedReason: '您没有查看该分类作品的权限'
              });
              return;
            }
          }
        }
      } else {
        // 作品公开，检查作品分类权限（如果有分类权限限制）
        const { userPermissions } = this.data;
        if (workData.type && userPermissions.categories && userPermissions.categories.length > 0) {
          if (!userPermissions.categories.includes(workData.type)) {
            // 用户没有查看该分类作品的权限
            wx.hideLoading();
            this.setData({
              isLoading: false,
              unauthorized: true,
              unauthorizedReason: '您没有查看该分类作品的权限'
            });
            return;
          }
        }
      }
      
      // 所有权限检查通过，加载完整内容
      // 加载相关项目
      this.loadRelatedProjects(workData.id, workData.type).then(relatedProjects => {
        this.setData({
          work: workData,
          relatedProjects: relatedProjects,
          isLoading: false,
          unauthorized: false,
          unauthorizedReason: ''
        });
        wx.hideLoading();
      });
    }).catch(err => {
      console.error('加载作品详情失败:', err);
      wx.hideLoading();
      this.setData({ isLoading: false });
      wx.showToast({
        title: '加载失败，请重试',
        icon: 'none'
      });
      setTimeout(() => {
        wx.navigateBack();
      }, 1500);
    });
  },

  /**
   * 加载相关项目
   */
  loadRelatedProjects(currentWorkId, workType) {
    return new Promise((resolve, reject) => {
      api.worksApi.getWorks({ type: workType }).then(res => {
        if (res.success && res.data) {
          // 过滤掉当前作品，只返回其他作品
          const relatedProjects = res.data.filter(work => work.id !== currentWorkId).slice(0, 2);
          resolve(relatedProjects);
        } else {
          resolve([]);
        }
      }).catch(() => {
        resolve([]);
      });
    });
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
    
    return processedHtml;
  },

  /**
   * 导航到相关项目
   */
  navigateToRelatedProject(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({
      url: `/pages/work-detail/work-detail?id=${id}`
    });
  },

  /**
   * 返回上级
   */
  navigateBack() {
    wx.navigateBack();
  },

  /**
   * 跳转到联系页面
   */
  goToContact() {
    wx.switchTab({
      url: '/pages/contact/contact',
      success: () => {
        console.log('成功跳转到联系页面');
      },
      fail: (err) => {
        console.error('跳转到联系页面失败:', err);
        wx.showToast({
          title: '跳转失败，请稍后重试',
          icon: 'error',
          duration: 2000
        });
      }
    });
  }
});
