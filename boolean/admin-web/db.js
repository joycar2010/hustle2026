const { Low } = require('lowdb');
const { JSONFile } = require('lowdb/node');
const path = require('path');
const bcrypt = require('bcrypt');
const saltRounds = 10;

// 数据库文件路径
const dbPath = path.join(__dirname, 'data', 'db.json');

// 定义默认数据结构
const defaultData = {
  users: [
    {
      id: 1,
      username: 'admin',
      password: '$2b$10$6t8Y8N1Z6q5r4e3w2q1a0s9d8f7g6h5j4k3l2m1n0b9v8c7x6d5c4v3b2n1m0',
      role: 'admin',
      permissions: {
        dashboard: true,
        works: true,
        categories: true,
        leads: true,
        customers: true,
        brand: true,
        stats: true,
        settings: true,
        users: true
      },
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    }
  ],
  logs: [],
  operationLogs: [],
  works: [
    {
      id: 1,
      title: '现代简约风格住宅',
      type: 'residential',
      area: 120,
      location: '北京',
      coverImage: 'https://via.placeholder.com/800x600?text=现代简约风格住宅',
      images: [
        'https://via.placeholder.com/800x600?text=现代简约风格住宅-1',
        'https://via.placeholder.com/800x600?text=现代简约风格住宅-2',
        'https://via.placeholder.com/800x600?text=现代简约风格住宅-3'
      ],
      description: '采用现代简约设计风格，注重空间利用和自然光线，营造舒适宜居的生活环境。',
      designPeriod: '6个月',
      style: '现代简约',
      designDescription: '本项目采用现代简约设计风格，以白色为主色调，搭配灰色和木色元素，营造出简洁、明亮的空间氛围。空间规划上注重功能性和流动性，通过开放式布局增强空间感，同时保留必要的隐私区域。',
      designConcept: '设计理念源于"少即是多"的现代主义思想，通过简洁的线条、纯净的色彩和实用的功能设计，创造出舒适、宜居的生活空间。强调自然光线的引入，通过大面积窗户和玻璃隔断，让空间更加通透和明亮。',
      functionPlanning: '空间功能规划合理，包括客厅、餐厅、厨房、主卧、次卧、书房和卫生间等功能区域。客厅采用开放式设计，与餐厅和厨房相连，增强空间的流动性和互动性。主卧配备独立卫生间和衣帽间，提供舒适的私人空间。书房设计兼顾工作和阅读功能，环境安静舒适。',
      materialSelection: '主要材料包括：白色乳胶漆墙面、灰色大理石地面、原木色实木地板、白色整体橱柜、灰色瓷砖卫生间墙面、不锈钢五金配件等。色彩搭配以白色为主，灰色和木色为辅，营造出简洁、现代的空间氛围。',
      highlights: [
        '开放式流动空间，视野更加开阔',
        '主次分明布局，功能分区合理',
        '自然光线引入，创造舒适氛围',
        '材质纹理对比，提升空间质感',
        '大面玻璃幕墙，充分采光通风'
      ],
      spaceType: '住宅',
      views: 125,
      isPublic: true,
      isFeatured: false,
      createdAt: '2024-01-15T10:30:00Z',
      updatedAt: '2024-01-15T10:30:00Z'
    },
    {
      id: 2,
      title: '高端写字楼设计',
      type: 'office',
      area: 500,
      location: '上海',
      coverImage: 'https://via.placeholder.com/800x600?text=高端写字楼设计',
      images: [
        'https://via.placeholder.com/800x600?text=高端写字楼设计-1',
        'https://via.placeholder.com/800x600?text=高端写字楼设计-2'
      ],
      description: '现代化办公空间，融合功能性与美学设计，提升员工工作效率和企业形象。',
      designPeriod: '4个月',
      style: '现代商务',
      designDescription: '本项目采用现代商务设计风格，以灰色和白色为主色调，搭配黑色和金属元素，营造出专业、高效的办公氛围。空间规划上注重功能性和灵活性，通过模块化设计适应不同的办公需求。',
      designConcept: '设计理念源于"高效协作"的现代办公思想，通过开放与封闭空间的合理搭配，创造出既有利于团队协作又保障个人专注的办公环境。强调科技感和专业性，通过现代化的设计元素提升企业形象。',
      functionPlanning: '空间功能规划包括前台接待区、开放式办公区、独立办公室、会议室、洽谈室、休闲区和茶水间等功能区域。开放式办公区采用模块化设计，可根据团队规模灵活调整。会议室配备现代化的会议设备，满足不同规模的会议需求。休闲区和茶水间提供舒适的休息空间，缓解工作压力。',
      materialSelection: '主要材料包括：灰色乳胶漆墙面、白色大理石地面、黑色玻璃隔断、不锈钢金属框架、灰色地毯、白色吸音天花板、LED筒灯等。色彩搭配以灰色和白色为主，黑色和金属色为辅，营造出专业、现代的办公氛围。',
      highlights: [
        '模块化办公空间，灵活适应不同需求',
        '开放与封闭空间合理搭配，平衡协作与专注',
        '现代化会议设施，提升会议效率',
        '舒适的休闲区域，缓解工作压力',
        '专业的前台形象，提升企业品牌价值'
      ],
      spaceType: '办公室',
      views: 98,
      isPublic: true,
      isFeatured: false,
      createdAt: '2024-01-10T14:20:00Z',
      updatedAt: '2024-01-10T14:20:00Z'
    },
    {
      id: 3,
      title: '时尚餐厅设计',
      type: 'commercial',
      area: 200,
      location: '广州',
      coverImage: 'https://via.placeholder.com/800x600?text=时尚餐厅设计',
      images: [
        'https://via.placeholder.com/800x600?text=时尚餐厅设计-1',
        'https://via.placeholder.com/800x600?text=时尚餐厅设计-2',
        'https://via.placeholder.com/800x600?text=时尚餐厅设计-3',
        'https://via.placeholder.com/800x600?text=时尚餐厅设计-4'
      ],
      description: '独特的空间设计，营造出时尚、舒适的用餐环境，吸引众多顾客。',
      designPeriod: '3个月',
      style: '工业风',
      designDescription: '本项目采用工业风设计风格，以裸露的砖墙、金属管道和木质元素为主，搭配暖色调灯光，营造出时尚、独特的用餐氛围。空间规划上注重层次感和流动感，通过不同高度的隔断和座位布局，创造出丰富的空间体验。',
      designConcept: '设计理念源于"原始与现代的融合"，通过裸露的建筑结构和现代的装饰元素，创造出独特的空间美学。强调用餐体验的个性化和氛围感，通过灯光、材质和布局的精心设计，为顾客提供难忘的用餐环境。',
      functionPlanning: '空间功能规划包括入口接待区、散座区、卡座区、VIP包厢、吧台和厨房等功能区域。散座区采用开放式设计，适合小团体用餐。卡座区提供相对私密的用餐空间，适合朋友聚会。VIP包厢配备独立的服务设施，适合商务宴请。吧台设计兼顾酒水服务和展示功能，成为餐厅的视觉焦点之一。',
      materialSelection: '主要材料包括：裸露砖墙、木质地板、金属管道、黑色铁艺家具、皮质座椅、复古灯具、工业风格吊灯等。色彩搭配以深棕色和黑色为主，暖黄色灯光为辅，营造出温馨、时尚的用餐氛围。',
      highlights: [
        '工业风设计，独特的空间美学',
        '多层次空间布局，丰富用餐体验',
        '暖色调灯光，营造温馨氛围',
        '裸露建筑结构，展现原始质感',
        '个性化卡座设计，提供私密空间'
      ],
      spaceType: '餐厅',
      views: 156,
      isPublic: true,
      isFeatured: false,
      createdAt: '2024-01-05T09:15:00Z',
      updatedAt: '2024-01-05T09:15:00Z'
    }
  ],
  categories: [
    {
      id: 1,
      name: '家装设计',
      slug: 'residential',
      description: '住宅空间设计，包括公寓、别墅、复式等',
      worksCount: 15,
      createdAt: '2024-01-01T09:00:00Z',
      updatedAt: '2024-01-01T09:00:00Z'
    },
    {
      id: 2,
      name: '公装设计',
      slug: 'office',
      description: '办公空间设计，包括写字楼、工作室等',
      worksCount: 5,
      createdAt: '2024-01-01T09:05:00Z',
      updatedAt: '2024-01-01T09:05:00Z'
    },
    {
      id: 3,
      name: '商业空间',
      slug: 'commercial',
      description: '商业空间设计，包括餐厅、商店、酒店等',
      worksCount: 4,
      createdAt: '2024-01-01T09:10:00Z',
      updatedAt: '2024-01-01T09:10:00Z'
    },
    {
      id: 4,
      name: '其他设计',
      slug: 'other',
      description: '其他类型的空间设计',
      worksCount: 0,
      createdAt: '2024-01-01T09:15:00Z',
      updatedAt: '2024-01-01T09:15:00Z'
    }
  ],
  leads: [
    {
      id: 1,
      name: '张三',
      phone: '13800138000',
      email: 'zhangsan@example.com',
      projectType: 'residential',
      budget: '10-20万',
      status: 'new',
      description: '需要家装设计服务，喜欢现代简约风格',
      wechatAvatar: '',
      wechatOpenId: '',
      wechatNickname: '',
      createdAt: '2024-01-15T10:30:00Z',
      updatedAt: '2024-01-15T10:30:00Z'
    },
    {
      id: 2,
      name: '李四',
      phone: '13900139000',
      email: 'lisi@example.com',
      projectType: 'office',
      budget: '50-80万',
      status: 'processing',
      description: '办公室装修设计，需要现代商务风格',
      wechatAvatar: '',
      wechatOpenId: '',
      wechatNickname: '',
      createdAt: '2024-01-14T14:20:00Z',
      updatedAt: '2024-01-14T14:20:00Z'
    },
    {
      id: 3,
      name: '王五',
      phone: '13700137000',
      email: 'wangwu@example.com',
      projectType: 'commercial',
      budget: '100-150万',
      status: 'completed',
      description: '餐厅设计，已经完成方案确认',
      wechatAvatar: '',
      wechatOpenId: '',
      wechatNickname: '',
      createdAt: '2024-01-13T09:15:00Z',
      updatedAt: '2024-01-13T16:45:00Z'
    },
    {
      id: 4,
      name: '赵六',
      phone: '13600136000',
      email: 'zhaoliu@example.com',
      projectType: 'residential',
      budget: '20-30万',
      status: 'canceled',
      description: '取消了服务，选择了其他设计公司',
      wechatAvatar: '',
      wechatOpenId: '',
      wechatNickname: '',
      createdAt: '2024-01-12T11:45:00Z',
      updatedAt: '2024-01-12T15:20:00Z'
    }
  ],
  settings: {
    siteName: '布珥·迈拓空间设计',
    siteLogo: '/images/logo.png',
    socialMedia: {
      wechat: 'space_design',
      weibo: '@space_design',
      instagram: 'space_design'
    },
    seoSettings: {
      title: '布珥·迈拓空间设计 - 高端空间设计服务',
      description: '专业的空间设计公司，提供家装、公装、商业空间设计服务',
      keywords: '空间设计, 家装设计, 公装设计, 商业空间设计'
    },
    notificationSettings: {
      leadNotification: true,
      workNotification: true,
      emailNotification: true
    }
  },
  about: {
    brandInfo: {
      name: '布珥设计',
      description: '布珥设计致力于打造集商业策划、建筑设计、室内设计、景观设计和施工落地于一体的设计与建造平台。我们拥有50多名专业设计师团队，与100多家供应商建立长期合作关系，确保每个项目都能完美落地。从2010年成立至今，我们已完成500多个设计项目，涵盖住宅、办公、商业等多个领域。我们的设计理念是“用设计重塑空间，让生活更美好”。',
      logo: '/images/logo.png',
      slogan: '用设计重塑空间，让生活更美好'
    },
    contactInfo: {
      phone: '400-123-4567',
      email: 'info@example.com',
      address1: '北京市朝阳区建国路88号',
      address2: '',
      workingHours: '周一至周日 9:00-21:00',
      map: 'https://maps.google.com/maps?q=北京市朝阳区建国路88号'
    },
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
        image: 'https://via.placeholder.com/800x600?text=张设计师'
      },
      {
        id: 2,
        name: '李设计师',
        position: '首席设计师',
        image: 'https://via.placeholder.com/800x600?text=李设计师'
      },
      {
        id: 3,
        name: '王设计师',
        position: '资深设计师',
        image: 'https://via.placeholder.com/800x600?text=王设计师'
      },
      {
        id: 4,
        name: '赵设计师',
        position: '设计师',
        image: 'https://via.placeholder.com/800x600?text=赵设计师'
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
    },
    companyPhotos: []
  },
  customers: [
    {
      id: 1,
      wechatAvatar: 'https://via.placeholder.com/100x100?text=Avatar',
      wechatNickname: '微信用户1',
      name: '张三',
      phone: '13800138000',
      email: 'zhangsan@example.com',
      customerType: '终端用户',
      permissions: {
        viewWorks: true,
        categories: ['residential', 'office']
      },
      createdAt: '2024-01-15T10:30:00Z',
      updatedAt: '2024-01-15T10:30:00Z'
    },
    {
      id: 2,
      wechatAvatar: 'https://via.placeholder.com/100x100?text=Avatar',
      wechatNickname: '微信用户2',
      name: '李四',
      phone: '13900139000',
      email: 'lisi@example.com',
      customerType: '经销商',
      permissions: {
        viewWorks: true,
        categories: ['residential', 'office', 'commercial']
      },
      createdAt: '2024-01-14T14:20:00Z',
      updatedAt: '2024-01-14T14:20:00Z'
    }
  ],
  customerCategories: [
    {
      id: 1,
      name: '经销商',
      description: '销售产品的经销商',
      createdAt: '2024-01-01T09:00:00Z',
      updatedAt: '2024-01-01T09:00:00Z'
    },
    {
      id: 2,
      name: '终端用户',
      description: '直接使用产品的终端用户',
      createdAt: '2024-01-01T09:05:00Z',
      updatedAt: '2024-01-01T09:05:00Z'
    }
  ],
  // 自增ID计数器
  counters: {
    work: 4,
    category: 5,
    lead: 5,
    customer: 3,
    customerCategory: 3
  }
};

// 初始化数据库实例
const adapter = new JSONFile(dbPath);
const db = new Low(adapter, defaultData);

// 初始化数据库数据
async function initDatabase() {
  await db.read();
  
  // 如果数据库为空，初始化默认数据
  if (!db.data || Object.keys(db.data).length === 0) {
    // 加密默认管理员密码
    const hashedPassword = await bcrypt.hash('admin123', saltRounds);
    defaultData.users[0].password = hashedPassword;
    db.data = defaultData;
    await db.write();
  } else {
    // 检查并添加缺失的字段
    if (!db.data.customers) {
      db.data.customers = defaultData.customers;
    }
    
    if (!db.data.customerCategories) {
      db.data.customerCategories = defaultData.customerCategories;
    }
    
    if (!db.data.counters) {
      db.data.counters = defaultData.counters;
    } else {
      // 检查并添加缺失的计数器
      if (!db.data.counters.customer) {
        db.data.counters.customer = defaultData.counters.customer;
      }
      
      if (!db.data.counters.customerCategory) {
        db.data.counters.customerCategory = defaultData.counters.customerCategory;
      }
    }
    
    // 检查并添加缺失的logs数组
    if (!db.data.logs) {
      db.data.logs = [];
    }
    
    // 保存数据库
    await db.write();
  }
}

// 获取下一个ID
function getNextId(type) {
  const id = db.data.counters[type] || 1;
  db.data.counters[type] = id + 1;
  return id;
}

// 导出数据库实例和辅助函数
module.exports = {
  db,
  initDatabase,
  getNextId
};
