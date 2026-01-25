const mongoose = require('mongoose');

const SettingSchema = new mongoose.Schema({
  siteName: {
    type: String,
    required: true,
    trim: true
  },
  siteLogo: {
    type: String,
    trim: true
  },
  contactEmail: {
    type: String,
    trim: true
  },
  contactPhone: {
    type: String,
    trim: true
  },
  address: {
    type: String,
    trim: true
  },
  socialMedia: {
    wechat: {
      type: String,
      trim: true
    },
    weibo: {
      type: String,
      trim: true
    },
    instagram: {
      type: String,
      trim: true
    }
  },
  seoSettings: {
    title: {
      type: String,
      trim: true
    },
    description: {
      type: String,
      trim: true
    },
    keywords: {
      type: String,
      trim: true
    }
  },
  notificationSettings: {
    leadNotification: {
      type: Boolean,
      default: true
    },
    workNotification: {
      type: Boolean,
      default: true
    },
    emailNotification: {
      type: Boolean,
      default: true
    }
  },
  createdAt: {
    type: Date,
    default: Date.now
  },
  updatedAt: {
    type: Date,
    default: Date.now
  }
});

module.exports = mongoose.model('Setting', SettingSchema);
