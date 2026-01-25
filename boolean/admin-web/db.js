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
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    }
  ],
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
      views: 125,
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
      views: 98,
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
      views: 156,
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
      createdAt: '2024-01-12T11:45:00Z',
      updatedAt: '2024-01-12T15:20:00Z'
    }
  ],
  settings: {
    siteName: '布珥·迈拓空间设计',
    siteLogo: '/images/logo.png',
    contactEmail: 'info@example.com',
    contactPhone: '400-123-4567',
    address: '北京市朝阳区建国路88号',
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
      name: '布珥·迈拓空间设计',
      description: '布珥·迈拓空间设计是一家专注于高端空间设计的专业公司，致力于为客户提供个性化、高品质的空间设计解决方案。我们拥有一支经验丰富的设计团队，能够满足各种空间设计需求，包括住宅、商业、办公等不同类型的空间。',
      logo: '/images/logo.png',
      slogan: '创造理想空间，提升生活品质'
    },
    contactInfo: {
      phone: '400-123-4567',
      email: 'info@example.com',
      address: '北京市朝阳区建国路88号布珥·迈拓空间设计中心',
      workingHours: '周一至周五 9:00-18:00',
      map: 'https://maps.google.com/maps?q=北京市朝阳区建国路88号'
    }
  },
  // 自增ID计数器
  counters: {
    work: 4,
    category: 5,
    lead: 5
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
