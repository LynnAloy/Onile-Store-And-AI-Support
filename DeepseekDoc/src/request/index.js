import axios from 'axios'

const getTest = function () {
   return axios.get('https://m1.apifoxmock.com/m1/6604794-6311003-default/axios_test')  
}

const getTest2 = function () {
   return axios.get('https://m1.apifoxmock.com/m1/6604794-6311003-default/axios_test')  
}

export default {getTest,getTest2};