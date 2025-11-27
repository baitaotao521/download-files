function c(u,t){return u.then(function(n){return[null,n]}).catch(function(n){return t&&Object.assign(n,t),[n,void 0]})}export{c as t};
