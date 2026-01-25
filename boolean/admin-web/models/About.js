const mongoose = require('mongoose');

const AboutSchema = new mongoose.Schema({
  brandInfo: {
    name: {
      type: String,
      required: true,
      trim: true
    },
    description: {
      type: String,
      trim: true
    },
    logo: {
      type: String,
      trim: true
    },
    slogan: {
      type: String,
      trim: true
    }
  },
  contactInfo: {
    phone: {
      type: String,
      trim: true
    },
    email: {
      type: String,
      trim: true
    },
    address: {
      type: String,
      trim: true
    },
    workingHours: {
      type: String,
      trim: true
    },
    map: {
      type: String,
      trim: true
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

module.exports = mongoose.model('About', AboutSchema);
