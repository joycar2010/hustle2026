// pages/brand/brand.js
const api = require('../../utils/api.js');

Page({
  /**
   * 页面的初始数据
   */
  data: {
    brandInfo: {
      name: '布珥·迈拓空间设计',
      description: '布珥·迈拓空间设计致力于打造集商业策划、建筑设计、室内设计、景观设计和施工落地于一体的设计与建造平台。我们拥有50多名专业设计师团队，与100多家供应商建立长期合作关系，确保每个项目都能完美落地。从2010年成立至今，我们已完成500多个设计项目，涵盖住宅、办公、商业等多个领域。我们的设计理念是“用设计重塑空间，让生活更美好”。',
      logo: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
    },
    companyPhotos: [],
    achievements: {
      designers: '50+',
      suppliers: '100+',
      projects: '500+',
      awards: '10+'
    },
    concepts: [
      {
        id: 1,
        title: '创意创新',
        description: '不断探索新的设计理念和技术应用，为客户提供创新的设计方案。'
      },
      {
        id: 2,
        title: '品质至上',
        description: '严格把控每一个细节，确保项目质量达到最高标准。'
      },
      {
        id: 3,
        title: '客户至上',
        description: '以客户需求为中心，为客户提供最优的设计体验。'
      },
      {
        id: 4,
        title: '团队合作',
        description: '发挥团队优势，通过协作为客户创造最大价值。'
      }
    ],
    process: [
      {
        id: 1,
        title: '项目咨询',
        description: '深入了解客户需求、预算、时间和设计偏好，为项目奠定坚实基础。'
      },
      {
        id: 2,
        title: '方案设计',
        description: '创意团队进行头脑风暴，制定多个设计方案供客户选择。'
      },
      {
        id: 3,
        title: '深化设计',
        description: '根据客户反馈，对选定方案进行深化和细化。'
      },
      {
        id: 4,
        title: '施工落地',
        description: '与施工团队紧密配合，确保设计完美落地。'
      },
      {
        id: 5,
        title: '项目验收',
        description: '进行最终验收，确保项目质量达到预期。'
      },
      {
        id: 6,
        title: '售后服务',
        description: '提供长期的售后服务和维护支持。'
      }
    ],
    team: [
      {
        id: 1,
        name: '张设计师',
        position: '创意总监',
        image: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
      },
      {
        id: 2,
        name: '李设计师',
        position: '首席设计师',
        image: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
      },
      {
        id: 3,
        name: '王设计师',
        position: '资深设计师',
        image: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
      },
      {
        id: 4,
        name: '赵设计师',
        position: '设计师',
        image: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
      }
    ],
    honors: [
      {
        id: 1,
        title: '中国设计大奖',
        description: '获得2023年中国设计大奖金奖',
        icon: '🏆'
      },
      {
        id: 2,
        title: '国际设计奖',
        description: '获得2023年国际设计奖银奖',
        icon: '⭐'
      },
      {
        id: 3,
        title: 'ISO认证',
        description: '通过ISO 9001质量管理体系认证',
        icon: '🏢'
      },
      {
        id: 4,
        title: '行业协会',
        description: '中国室内装饰协会会员单位',
        icon: '🌟'
      }
    ],
    partners: {
      description: '我们与100多家知名供应商和施工单位建立了长期合作关系，包括国际一线家具品牌、高端建材供应商、专业施工团队等，为客户提供最优质的产品和服务。',
      list: [
        '合作伙伴 1',
        '合作伙伴 2',
        '合作伙伴 3',
        '合作伙伴 4',
        '合作伙伴 5',
        '合作伙伴 6',
        '合作伙伴 7',
        '合作伙伴 8'
      ]
    },
    cooperation: {
      title: '准备与我们合作？',
      description: '联系我们的设计团队，为您打造独特的空间设计方案'
    }
  },

  /**
   * 生命周期函数--监听页面加载
   */
  onLoad(options) {
    this.loadBrandInfo();
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
    this.loadBrandInfo();
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
    this.loadBrandInfo();
    wx.stopPullDownRefresh();
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
   * 页面上拉触底事件的处理函数
   */
  onReachBottom() {

  },

  /**
   * 用户点击右上角分享
   */
  onShareAppMessage() {
    return {
      title: '布珥·迈拓空间设计 - 关于我们',
      path: '/pages/brand/brand'
    };
  },

  /**
   * 加载品牌信息
   */
  loadBrandInfo() {
    wx.showLoading({
      title: '加载中...'
    });

    api.aboutApi.getAboutInfo()
      .then(res => {
        wx.hideLoading();
        if (res && res.success && res.data) {
          // 确保数据结构正确
          const data = res.data;
          this.setData({
            brandInfo: data.brandInfo || this.data.brandInfo,
            achievements: data.achievements || this.data.achievements,
            concepts: data.concepts || this.data.concepts,
            process: data.process || this.data.process,
            team: data.team || this.data.team,
            honors: data.honors || this.data.honors,
            partners: data.partners || this.data.partners,
            cooperation: data.cooperation || this.data.cooperation,
            companyPhotos: data.companyPhotos || this.data.companyPhotos
          });
        } else {
          wx.showToast({
            title: '数据格式错误',
            icon: 'none',
            duration: 2000
          });
        }
      })
      .catch(err => {
        wx.hideLoading();
        console.error('加载品牌信息失败:', err);
        wx.showToast({
          title: '加载失败，显示默认信息',
          icon: 'none',
          duration: 2000
        });
      });
  }
});
