// pages/index/index.js
const api = require('../../utils/api');

Page({
  /**
   * 页面的初始数据
   */
  data: {
    featuredWorks: [],
    coverPhoto: null
  },

  /**
   * 生命周期函数--监听页面加载
   */
  onLoad(options) {
    this.loadFeaturedWorks();
    this.loadCoverPhoto();
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
    // 每次页面显示时重新加载数据，确保获取最新版本
    this.loadFeaturedWorks();
    this.loadCoverPhoto();
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
    this.loadFeaturedWorks();
    this.loadCoverPhoto();
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
      title: '布珥·迈拓空间设计 - 用设计重塑空间，让生活更美好',
      path: '/pages/index/index'
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
   * 加载精选作品
   */
  loadFeaturedWorks() {
    // 传递featured=true参数，获取精选作品
    api.worksApi.getWorks({ featured: true }).then(res => {
      // 处理作品数据，验证图片URL
      const processedWorks = res.data.map(work => {
        // 处理图片数据
        const validImages = [];
        
        // 先检查coverImage字段
        if (work.coverImage && this.validateImageUrl(work.coverImage)) {
          validImages.push(work.coverImage);
        }
        
        // 再检查images数组
        if (work.images && Array.isArray(work.images)) {
          work.images.forEach(imageUrl => {
            if (this.validateImageUrl(imageUrl)) {
              validImages.push(imageUrl);
            }
          });
        }
        
        work.images = validImages;
        return work;
      }).slice(0, 3); // 只显示3个精选作品
      
      this.setData({
        featuredWorks: processedWorks
      });
    }).catch(err => {
      console.error('加载精选作品失败:', err);
      // 错误处理：显示友好提示
      wx.showToast({
        title: '加载精选作品失败',
        icon: 'none',
        duration: 2000
      });
    });
  },

  /**
   * 跳转到品牌页面
   */
  goToBrand() {
    wx.switchTab({
      url: '/pages/brand/brand',
      success: () => {
        console.log('成功跳转到品牌页面');
      },
      fail: (err) => {
        console.error('跳转到品牌页面失败:', err);
        wx.showToast({
          title: '跳转失败，请稍后重试',
          icon: 'error',
          duration: 2000
        });
      }
    });
  },

  /**
   * 加载首页封面照片
   */
  loadCoverPhoto() {
    api.aboutApi.getAboutInfo()
      .then(res => {
        if (res && res.success && res.data && res.data.companyPhotos) {
          // 找到设置为封面的照片
          const coverPhoto = res.data.companyPhotos.find(photo => photo.isCover);
          if (coverPhoto) {
            this.setData({
              coverPhoto: coverPhoto
            });
          }
        }
      })
      .catch(err => {
        console.error('加载封面照片失败:', err);
      });
  },

  /**
   * 跳转到作品页面
   */
  goToWorks(e) {
    const type = e.currentTarget.dataset.type;
    // 使用wx.switchTab跳转到作品页面
    wx.switchTab({
      url: '/pages/works/works',
      success: () => {
        // 跳转到作品页面后，设置筛选类型
        const pages = getCurrentPages();
        const worksPage = pages[pages.length - 1];
        if (worksPage && worksPage.setFilterType) {
          worksPage.setFilterType({ currentTarget: { dataset: { type } } });
        }
      },
      fail: (err) => {
        console.error('跳转到作品页面失败:', err);
        wx.showToast({
          title: '跳转失败，请稍后重试',
          icon: 'error',
          duration: 2000
        });
      }
    });
  },

  /**
   * 跳转到全部作品页面
   */
  goToAllWorks() {
    wx.switchTab({
      url: '/pages/works/works',
      success: () => {
        // 跳转到作品页面后，设置筛选类型为全部
        const pages = getCurrentPages();
        const worksPage = pages[pages.length - 1];
        if (worksPage && worksPage.setFilterType) {
          worksPage.setFilterType({ currentTarget: { dataset: { type: '' } } });
        }
        console.log('成功跳转到全部作品页面');
      },
      fail: (err) => {
        console.error('跳转到全部作品页面失败:', err);
        wx.showToast({
          title: '跳转失败，请稍后重试',
          icon: 'error',
          duration: 2000
        });
      }
    });
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
