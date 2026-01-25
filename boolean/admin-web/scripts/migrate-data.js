const mongoose = require('mongoose');

// 导入数据模型
const User = require('../models/User');
const Work = require('../models/Work');
const Category = require('../models/Category');
const Lead = require('../models/Lead');
const Setting = require('../models/Setting');
const About = require('../models/About');

// 连接MongoDB数据库
mongoose.connect('mongodb://localhost:27017/space-design-db')
.then(() => console.log('MongoDB连接成功'))
.catch(err => console.error('MongoDB连接失败:', err));

// 模拟数据
const mockData = {
  // 用户数据
  user: {
    username: 'admin',
    password: 'admin123',
    role: 'admin'
  },
  
  // 分类数据
  categories: [
    {
      name: '家装设计',
      slug: 'residential',
      description: '住宅空间设计，包括公寓、别墅、复式等',
      worksCount: 15
    },
    {
      name: '公装设计',
      slug: 'office',
      description: '办公空间设计，包括写字楼、工作室等',
      worksCount: 5
    },
    {
      name: '商业空间',
      slug: 'commercial',
      description: '商业空间设计，包括餐厅、商店、酒店等',
      worksCount: 4
    },
    {
      name: '其他设计',
      slug: 'other',
      description: '其他类型的空间设计',
      worksCount: 0
    }
  ],
  
  // 作品数据
  works: [
    {
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
      views: 125
    },
    {
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
      views: 98
    },
    {
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
      views: 156
    }
  ],
  
  // 线索数据
  leads: [
    {
      name: '张三',
      phone: '13800138000',
      email: 'zhangsan@example.com',
      projectType: 'residential',
      budget: '10-20万',
      status: 'new',
      description: '需要家装设计服务，喜欢现代简约风格'
    },
    {
      name: '李四',
      phone: '13900139000',
      email: 'lisi@example.com',
      projectType: 'office',
      budget: '50-80万',
      status: 'processing',
      description: '办公室装修设计，需要现代商务风格'
    },
    {
      name: '王五',
      phone: '13700137000',
      email: 'wangwu@example.com',
      projectType: 'commercial',
      budget: '100-150万',
      status: 'completed',
      description: '餐厅设计，已经完成方案确认'
    },
    {
      name: '赵六',
      phone: '13600136000',
      email: 'zhaoliu@example.com',
      projectType: 'residential',
      budget: '20-30万',
      status: 'canceled',
      description: '取消了服务，选择了其他设计公司'
    }
  ],
  
  // 系统设置数据
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
  
  // 关于我们数据
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
  }
};

// 数据迁移函数
async function migrateData() {
  try {
    console.log('开始数据迁移...');
    
    // 1. 清空现有数据
    await User.deleteMany();
    await Category.deleteMany();
    await Work.deleteMany();
    await Lead.deleteMany();
    await Setting.deleteMany();
    await About.deleteMany();
    
    console.log('现有数据已清空');
    
    // 2. 导入用户数据
    const user = new User(mockData.user);
    await user.save();
    console.log('用户数据导入成功');
    
    // 3. 导入分类数据
    for (const categoryData of mockData.categories) {
      const category = new Category(categoryData);
      await category.save();
    }
    console.log('分类数据导入成功');
    
    // 4. 导入作品数据
    for (const workData of mockData.works) {
      const work = new Work(workData);
      await work.save();
    }
    console.log('作品数据导入成功');
    
    // 5. 导入线索数据
    for (const leadData of mockData.leads) {
      const lead = new Lead(leadData);
      await lead.save();
    }
    console.log('线索数据导入成功');
    
    // 6. 导入系统设置数据
    const setting = new Setting(mockData.settings);
    await setting.save();
    console.log('系统设置数据导入成功');
    
    // 7. 导入关于我们数据
    const about = new About(mockData.about);
    await about.save();
    console.log('关于我们数据导入成功');
    
    console.log('数据迁移完成！');
    
    // 断开数据库连接
    mongoose.connection.close();
  } catch (error) {
    console.error('数据迁移失败:', error);
    mongoose.connection.close();
  }
}

// 执行数据迁移
migrateData();
